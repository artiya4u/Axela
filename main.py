#! /usr/bin/env python

import os
import time
import sys
import alsaaudio
import requests
import json
from memcache import Client
import vlc
import threading
import email
import optparse

import tunein
import webrtcvad

from pocketsphinx.pocketsphinx import *

from creds import *

# Settings
device = "pulse"  # Name of your microphone/sound card in arecord -L , Using Pulse audio by default

# Get arguments
parser = optparse.OptionParser()
parser.add_option('-s', '--silent',
                  dest="silent",
                  action="store_true",
                  default=False,
                  help="start without saying hello"
                  )
parser.add_option('-d', '--debug',
                  dest="debug",
                  action="store_true",
                  default=True,
                  help="display debug messages"
                  )

cmdopts, cmdargs = parser.parse_args()
silent = cmdopts.silent
debug = cmdopts.debug

# Setup
recorded = False
servers = ["127.0.0.1:11211"]
mc = Client(servers, debug=1)
path = os.path.realpath(__file__).rstrip(os.path.basename(__file__))

# Sphinx setup
trigger_phrase = "Axela"

sphinx_data_path = path + "pocketsphinx/"
model_dir = sphinx_data_path + "/model/"
data_dir = sphinx_data_path + "/test/data"

# PocketSphinx configuration
config = Decoder.default_config()

# Set recognition model to US
config.set_string('-hmm', os.path.join(model_dir, 'en-us/en-us'))
config.set_string('-dict', os.path.join(model_dir, 'en-us/cmudict-en-us.dict'))

# Specify recognition key phrase
config.set_string('-keyphrase', trigger_phrase)
config.set_float('-kws_threshold', 1e-5)

# Hide the VERY verbose logging information
config.set_string('-logfn', '/dev/null')

# Process audio chunk by chunk. On keyword detected perform action and restart search
decoder = Decoder(config)
decoder.start_utt()

# Variables
p = ""
nav_token = ""
stream_url = ""
stream_id = ""
position = 0
audio_playing = False
button_pressed = False
start = time.time()
tunein_parser = tunein.TuneIn(5000)
vad = webrtcvad.Vad(2)
currVolume = 100

# constants 
VAD_SAMPLERATE = 16000
VAD_FRAME_MS = 30
VAD_PERIOD = (VAD_SAMPLERATE / 1000) * VAD_FRAME_MS
VAD_SILENCE_TIMEOUT = 1000
VAD_THROWAWAY_FRAMES = 10
MAX_RECORDING_LENGTH = 8
MAX_VOLUME = 100
MIN_VOLUME = 30


class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def internet_on():
    print("Checking Internet Connection...")
    try:
        r = requests.get('https://api.amazon.com/auth/o2/token')
        print("Connection {}OK{}".format(bcolors.OKGREEN, bcolors.ENDC))
        return True
    except:
        print("Connection {}Failed{}".format(bcolors.WARNING, bcolors.ENDC))
        return False


def gettoken():
    token = mc.get("access_token")
    refresh = refresh_token
    if token:
        return token
    elif refresh:
        payload = {"client_id": Client_ID, "client_secret": Client_Secret, "refresh_token": refresh,
                   "grant_type": "refresh_token", }
        url = "https://api.amazon.com/auth/o2/token"
        r = requests.post(url, data=payload)
        resp = json.loads(r.text)
        mc.set("access_token", resp['access_token'], 3570)
        return resp['access_token']
    else:
        return False


def alexa_speech_recognizer():
    # https://developer.amazon.com/public/solutions/alexa/alexa-voice-service/rest/speechrecognizer-requests
    if debug:
        print("{}Sending Speech Request...{}".format(bcolors.OKBLUE, bcolors.ENDC))
    start_time = time.time()
    url = 'https://access-alexa-na.amazon.com/v1/avs/speechrecognizer/recognize'
    headers = {'Authorization': 'Bearer %s' % gettoken()}
    d = {
        "messageHeader": {
            "deviceContext": [
                {
                    "name": "playbackState",
                    "namespace": "AudioPlayer",
                    "payload": {
                        "streamId": "",
                        "offsetInMilliseconds": "0",
                        "playerActivity": "IDLE"
                    }
                }
            ]
        },
        "messageBody": {
            "profile": "alexa-close-talk",
            "locale": "en-us",
            "format": "audio/L16; rate=16000; channels=1"
        }
    }
    with open(path + 'media/recording.wav') as inf:
        files = [
            ('file', ('request', json.dumps(d), 'application/json; charset=UTF-8')),
            ('file', ('audio', inf, 'audio/L16; rate=16000; channels=1'))
        ]
        r = requests.post(url, headers=headers, files=files)
    if debug:
        print("{}Responded...{} Took {} secs".format(bcolors.OKBLUE, bcolors.ENDC, time.time() - start_time))
    process_response(r)


def alexa_getnextitem(nav_token):
    # https://developer.amazon.com/public/solutions/alexa/alexa-voice-service/rest/audioplayer-getnextitem-request
    time.sleep(0.5)
    if not audio_playing:
        if debug:
            print("{}Sending GetNextItem Request...{}".format(bcolors.OKBLUE, bcolors.ENDC))
        url = 'https://access-alexa-na.amazon.com/v1/avs/audioplayer/getNextItem'
        headers = {'Authorization': 'Bearer %s' % gettoken(), 'content-type': 'application/json; charset=UTF-8'}
        d = {
            "messageHeader": {},
            "messageBody": {
                "navigationToken": nav_token
            }
        }
        r = requests.post(url, headers=headers, data=json.dumps(d))
        process_response(r)


def alexa_playback_progress_report_request(request_type, player_activity, stream_id):
    # https://developer.amazon.com/public/solutions/alexa/alexa-voice-service/rest/audioplayer-events-requests
    # streamId                  Specifies the identifier for the current stream.
    # offsetInMilliseconds      Specifies the current position in the track, in milliseconds.
    # playerActivity            IDLE, PAUSED, or PLAYING
    if debug: print("{}Sending Playback Progress Report Request...{}".format(bcolors.OKBLUE, bcolors.ENDC))
    headers = {'Authorization': 'Bearer %s' % gettoken()}
    d = {
        "messageHeader": {},
        "messageBody": {
            "playbackState": {
                "streamId": stream_id,
                "offsetInMilliseconds": 0,
                "playerActivity": player_activity.upper()
            }
        }
    }

    if request_type.upper() == "ERROR":
        # The Playback Error method sends a notification to AVS
        # that the audio player has experienced an issue during playback.
        url = "https://access-alexa-na.amazon.com/v1/avs/audioplayer/playbackError"
    elif request_type.upper() == "FINISHED":
        # The Playback Finished method sends a notification to AVS
        # that the audio player has completed playback.
        url = "https://access-alexa-na.amazon.com/v1/avs/audioplayer/playbackFinished"
    elif request_type.upper() == "IDLE":
        # The Playback Idle method sends a notification to AVS
        # that the audio player has reached the end of the playlist.
        url = "https://access-alexa-na.amazon.com/v1/avs/audioplayer/playbackIdle"
    elif request_type.upper() == "INTERRUPTED":
        # The Playback Interrupted method sends a notification to AVS that the audio player has been interrupted. 
        # Note: The audio player may have been interrupted by a previous stop Directive.
        url = "https://access-alexa-na.amazon.com/v1/avs/audioplayer/playbackInterrupted"
    elif request_type.upper() == "PROGRESS_REPORT":
        # The Playback Progress Report method sends a notification to AVS with the current state of the audio player.
        url = "https://access-alexa-na.amazon.com/v1/avs/audioplayer/playbackProgressReport"
    elif request_type.upper() == "STARTED":
        # The Playback Started method sends a notification to AVS that the audio player has started playing.
        url = "https://access-alexa-na.amazon.com/v1/avs/audioplayer/playbackStarted"

    r = requests.post(url, headers=headers, data=json.dumps(d))
    if r.status_code != 204:
        print("{}(alexa_playback_progress_report_request Response){} {}".format(bcolors.WARNING, bcolors.ENDC, r))
    else:
        if debug: print(
            "{}Playback Progress Report was {}Successful!{}".format(bcolors.OKBLUE, bcolors.OKGREEN, bcolors.ENDC))


def process_response(r):
    global nav_token, stream_url, stream_id, currVolume, isMute
    if debug: print("{}Processing Request Response...{}".format(bcolors.OKBLUE, bcolors.ENDC))
    nav_token = ""
    stream_url = ""
    stream_id = ""
    if r.status_code == 200:
        data = "Content-Type: " + r.headers['content-type'] + '\r\n\r\n' + r.content
        msg = email.message_from_string(data)
        for payload in msg.get_payload():
            if payload.get_content_type() == "application/json":
                j = json.loads(payload.get_payload())
                if debug: print("{}JSON String Returned:{} {}".format(bcolors.OKBLUE, bcolors.ENDC, json.dumps(j)))
            elif payload.get_content_type() == "audio/mpeg":
                filename = path + "tmpcontent/" + payload.get('Content-ID').strip("<>") + ".mp3"
                with open(filename, 'wb') as f:
                    f.write(payload.get_payload())
            else:
                if debug: print(
                    "{}NEW CONTENT TYPE RETURNED: {} {}".format(bcolors.WARNING, bcolors.ENDC,
                                                                payload.get_content_type()))
        # Now process the response
        if 'directives' in j['messageBody']:
            if len(j['messageBody']['directives']) == 0:
                if debug:
                    print("0 Directives received")
            for directive in j['messageBody']['directives']:
                if directive['namespace'] == 'SpeechSynthesizer':
                    if directive['name'] == 'speak':
                        play_audio(path + "tmpcontent/" + directive['payload']['audioContent'].lstrip("cid:") + ".mp3")
                    for directive in j['messageBody']['directives']:  # if Alexa expects a response
                        # this is included in the same string as above if a response was expected
                        if directive['namespace'] == 'SpeechRecognizer':
                            if directive['name'] == 'listen':
                                if debug:
                                    timeout = directive['payload']['timeoutIntervalInMillis']
                                    print("{}Further Input Expected, timeout in: {} {}ms".format(bcolors.OKBLUE,
                                                                                                 bcolors.ENDC,
                                                                                                 timeout))
                                play_audio(path + 'media/beep.wav', 0, 100)
                                timeout = directive['payload']['timeoutIntervalInMillis'] / 116
                                # listen until the timeout from Alexa
                                silence_listener(timeout)
                                # now process the response
                                alexa_speech_recognizer()
                elif directive['namespace'] == 'AudioPlayer':
                    # do audio stuff - still need to honor the playBehavior
                    if directive['name'] == 'play':
                        nav_token = directive['payload']['navigationToken']
                        for stream in directive['payload']['audioItem']['streams']:
                            if stream['progressReportRequired']:
                                stream_id = stream['streamId']
                                playBehavior = directive['payload']['playBehavior']
                            if stream['streamUrl'].startswith("cid:"):
                                content = path + "tmpcontent/" + stream['streamUrl'].lstrip("cid:") + ".mp3"
                            else:
                                content = stream['streamUrl']
                            p_thread = threading.Thread(target=play_audio,
                                                        args=(content, stream['offsetInMilliseconds']))
                            p_thread.start()
                elif directive['namespace'] == "Speaker":
                    # speaker control such as volume
                    if directive['name'] == 'SetVolume':
                        vol_token = directive['payload']['volume']
                        type_token = directive['payload']['adjustmentType']
                        if type_token == 'relative':
                            currVolume += int(vol_token)
                        else:
                            currVolume = int(vol_token)

                        if currVolume > MAX_VOLUME:
                            currVolume = MAX_VOLUME
                        elif currVolume < MIN_VOLUME:
                            currVolume = MIN_VOLUME

                        if debug: print("new volume = {}".format(currVolume))

        elif 'audioItem' in j['messageBody']:  # Additional Audio Iten
            nav_token = j['messageBody']['navigationToken']
            for stream in j['messageBody']['audioItem']['streams']:
                if stream['progressReportRequired']:
                    stream_id = stream['streamId']
                if stream['streamUrl'].startswith("cid:"):
                    content = path + "tmpcontent/" + stream['streamUrl'].lstrip("cid:") + ".mp3"
                else:
                    content = stream['streamUrl']
                p_thread = threading.Thread(target=play_audio, args=(content, stream['offsetInMilliseconds']))
                p_thread.start()

        return
    elif r.status_code == 204:
        if debug:
            print("{}Request Response is null {}(This is OKAY!){}".format(bcolors.OKBLUE,
                                                                          bcolors.OKGREEN,
                                                                          bcolors.ENDC))
    else:
        print("{}(process_response Error){} Status Code: {}".format(bcolors.WARNING,
                                                                    bcolors.ENDC,
                                                                    r.status_code))
        r.connection.close()


def play_audio(file_name, offset=0, over_ride_volume=0):
    global currVolume
    if file_name.find('radiotime.com') != -1:
        file_name = tunein_playlist(file_name)
    global nav_token, p, audio_playing
    if debug:
        print("{}Play_Audio Request for:{} {}".format(bcolors.OKBLUE, bcolors.ENDC, file_name))

    i = vlc.Instance('--aout=alsa')  # , '--alsa-audio-device=mono', '--file-logging', '--logfile=vlc-log.txt')
    m = i.media_new(file_name)
    p = i.media_player_new()
    p.set_media(m)
    mm = m.event_manager()
    mm.event_attach(vlc.EventType.MediaStateChanged, state_callback, p)
    audio_playing = True

    if over_ride_volume == 0:
        p.audio_set_volume(currVolume)
    else:
        p.audio_set_volume(over_ride_volume)

    p.play()
    while audio_playing:
        continue


def tunein_playlist(url):
    global tunein_parser
    if debug:
        print("TUNE IN URL = {}".format(url))
    req = requests.get(url)
    lines = req.content.split('\n')

    nurl = tunein_parser.parse_stream_url(lines[0])
    if len(nurl) != 0:
        return nurl[0]

    return ""


def state_callback(event, player):
    global nav_token, audio_playing, stream_url, stream_id
    state = player.get_state()
    # 0: 'NothingSpecial'
    # 1: 'Opening'
    # 2: 'Buffering'
    # 3: 'Playing'
    # 4: 'Paused'
    # 5: 'Stopped'
    # 6: 'Ended'
    # 7: 'Error'
    if debug: print("{}Player State:{} {}".format(bcolors.OKGREEN, bcolors.ENDC, state))
    if state == 3:  # Playing
        if stream_id != "":
            r_thread = threading.Thread(target=alexa_playback_progress_report_request,
                                        args=("STARTED", "PLAYING", stream_id))
            r_thread.start()
    elif state == 5:  # Stopped
        audio_playing = False
        if stream_id != "":
            r_thread = threading.Thread(target=alexa_playback_progress_report_request,
                                        args=("INTERRUPTED", "IDLE", stream_id))
            r_thread.start()
        stream_url = ""
        stream_id = ""
        nav_token = ""
    elif state == 6:  # Ended
        audio_playing = False
        if stream_id != "":
            r_thread = threading.Thread(target=alexa_playback_progress_report_request,
                                        args=("FINISHED", "IDLE", stream_id))
            r_thread.start()
            stream_id = ""
        if stream_url != "":
            p_thread = threading.Thread(target=play_audio, args=(stream_url,))
            stream_url = ""
            p_thread.start()
        elif nav_token != "":
            g_thread = threading.Thread(target=alexa_getnextitem, args=(nav_token,))
            g_thread.start()
    elif state == 7:
        audio_playing = False
        if stream_id != "":
            r_thread = threading.Thread(target=alexa_playback_progress_report_request,
                                        args=("ERROR", "IDLE", stream_id))
            r_thread.start()
        stream_url = ""
        stream_id = ""
        nav_token = ""


def silence_listener(throwaway_frames):
    global button_pressed
    # Reenable reading microphone raw data
    inp = alsaaudio.PCM(alsaaudio.PCM_CAPTURE, alsaaudio.PCM_NORMAL, device)
    inp.setchannels(1)
    inp.setrate(VAD_SAMPLERATE)
    inp.setformat(alsaaudio.PCM_FORMAT_S16_LE)
    inp.setperiodsize(VAD_PERIOD)
    audio = ""

    # Buffer as long as we haven't heard enough silence or the total size is within max size
    threshold_silence_met = False
    frames = 0
    num_silence_runs = 0
    silence_run = 0
    start_time = time.time()

    # do not count first 10 frames when doing VAD
    while frames < throwaway_frames:  # VAD_THROWAWAY_FRAMES):
        l, data = inp.read()
        frames += 1
        if l:
            audio += data
            is_speech = vad.is_speech(data, VAD_SAMPLERATE)

    # now do VAD
    while button_pressed or ((not threshold_silence_met) and ((time.time() - start_time) < MAX_RECORDING_LENGTH)):
        l, data = inp.read()
        if l:
            audio += data
            if l == VAD_PERIOD:
                is_speech = vad.is_speech(data, VAD_SAMPLERATE)

                if not is_speech:
                    silence_run += 1
                    sys.stdout.write("_")
                else:
                    silence_run = 0
                    num_silence_runs += 1
                    sys.stdout.write("^")

        # only count silence runs after the first one
        # (allow user to speak for total of max recording length if they haven't said anything yet)
        if (num_silence_runs != 0) and ((silence_run * VAD_FRAME_MS) > VAD_SILENCE_TIMEOUT):
            threshold_silence_met = True

    if debug:
        print ("Debug: End recording")

    if debug:
        play_audio(path + 'media/beep.wav', 0, 100)
    rf = open(path + 'media/recording.wav', 'w')
    rf.write(audio)
    rf.close()
    inp.close()


def start():
    global audio_playing, p, vad, button_pressed
    while True:
        record_audio = False
        # Enable reading microphone raw data
        inp = alsaaudio.PCM(alsaaudio.PCM_CAPTURE, alsaaudio.PCM_NORMAL, device)
        inp.setchannels(1)
        inp.setrate(16000)
        inp.setformat(alsaaudio.PCM_FORMAT_S16_LE)
        inp.setperiodsize(1024)
        audio = ""
        start_time = time.time()

        while not record_audio:
            time.sleep(.1)
            # Process microphone audio via PocketSphinx, listening for trigger word
            while decoder.hyp() is None and button_pressed is False:
                # Read from microphone
                l, buf = inp.read()
                # Detect if keyword/trigger word was said
                decoder.process_raw(buf, False, False)

            # if trigger word was said
            if decoder.hyp() is not None:
                if audio_playing:
                    p.stop()
                start_time = time.time()
                record_audio = True
                play_audio(path + 'media/alexayes.mp3', 0)
            elif button_pressed:
                if audio_playing:
                    p.stop()
                record_audio = True

        # do the following things if either the button has been pressed or the trigger word has been said
        if debug:
            print ("detected the edge, setting up audio")

        # To avoid overflows close the microphone connection
        inp.close()

        # clean up the temp directory
        if not debug:
            os.system("rm " + path + "/tmpcontent/*")

        if debug:
            print("Starting to listen...")

        silence_listener(VAD_THROWAWAY_FRAMES)

        if debug:
            print("Debug: Sending audio to be processed")

        alexa_speech_recognizer()

        # Now that request is handled restart audio decoding
        decoder.end_utt()
        decoder.start_utt()


def setup():
    while not internet_on():
        print(".")
    token = gettoken()
    if not token:
        while True:
            for x in range(0, 5):
                time.sleep(.1)
                time.sleep(.1)
    for x in range(0, 5):
        time.sleep(.1)
        time.sleep(.1)
    if not silent:
        play_audio(path + "media/hello.mp3")


if __name__ == "__main__":
    setup()
    start()
