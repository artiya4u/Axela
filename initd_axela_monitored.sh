#! /bin/bash

### BEGIN INIT INFO
# Provides:          Axela
# Required-Start:    $all
# Required-Stop:     $all
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# Short-Description: Axela Service
# Description:       Start / Stop Axela Service
### END INIT INFO

exec > /var/log/Axela.log 2>&1 
case "$1" in

start)
    echo "Starting Axela..."
    python /opt/Axela/main.py &
    /opt/Axela/monitorAxela.sh &
;;

silent)
    echo "Starting Axela in silent mode..."
    python /opt/Axela/main.py -s &
;;

stop)
    echo "Stopping Axela.."
    pkill -f Axela\/main\.py
;;

restart|force-reload)
        echo "Restarting Axela.."
        $0 stop
        sleep 2
        $0 start
        echo "Restarted."
;;
*)
        echo "Usage: $0 {start|silent|stop|restart}"
        exit 1
esac
