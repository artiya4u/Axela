# Axela

Linux voice assistant
---------------------

### Requirements

* A Debian base Linux PC that support mic and speaker.


Next you need to obtain a set of credentials from Amazon to use the Alexa Voice service,
login at http://developer.amazon.com and Goto Alexa then Alexa Voice Service
You need to create a new product type as a Device, for the ID use something like Axela,
create a new security profile and under the web settings allowed origins put http://localhost:5050
and as a return URL put http://localhost:5050/code
Make a note of these credentials you will be asked for them during the install process

### Installation

Clone this repo to /opt/Axela

`sudo git clone https://github.com/artiya4u/Axela.git /opt/Axela`

Run the setup script

`./setup.sh`