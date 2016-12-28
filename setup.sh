#! /bin/bash
cwd=`pwd`
if [ "$EUID" -ne 0 ]
	then echo "Please run as root"
	exit
fi

chmod +x *.sh

read -p "Would you like to add always-on monitoring (y/N)? " monitor_axela

case ${monitor_axela} in
        [yY] ) 
        	echo "monitoring WILL be installed."
        ;;
        * )
        	echo "monitoring will NOT be installed."
        ;;
esac

apt-get update
apt-get install wget git -y

cd /opt

echo "--copying pocketsphinx--"
git clone https://github.com/cmusphinx/pocketsphinx.git

cd $cwd

wget --output-document vlc.py "http://git.videolan.org/?p=vlc/bindings/python.git;a=blob_plain;f=generated/vlc.py;hb=HEAD"
apt-get install python-dev swig libasound2-dev memcached python-pip python-alsaaudio vlc libpulse-dev -y
pip install -r requirements.txt
touch /var/log/axela.log

case ${monitor_axela} in
        [yY] ) 
		cp initd_axela_monitored.sh /etc/init.d/Axela
	;;
        * )
		cp initd_axela.sh /etc/init.d/Axela
        ;;
esac

update-rc.d Axela defaults

echo "--Creating creds.py--"
echo "Enter your Device Type ID:"
read productid
echo ProductID = \"$productid\" > creds.py

echo "Enter your Security Profile Description:"
read spd
echo Security_Profile_Description = \"$spd\" >> creds.py

echo "Enter your Security Profile ID:"
read spid
echo Security_Profile_ID = \"$spid\" >> creds.py

echo "Enter your Client ID:"
read cid
echo Client_ID = \"$cid\" >> creds.py

echo "Enter your Client Secret:"
read secret
echo Client_Secret = \"$secret\" >> creds.py

python ./auth_web.py 
