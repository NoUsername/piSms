# PiSms
The small and simple sms gateway

I am using PiSms on my RaspberryPi to send and receive sms.
It connects directly to the USB-Modem and communicates with it via the virtual serial port.
Because usb-modems sometimes hang, it has usb-modem-reset built in. It uses [this](https://gist.github.com/NoUsername/018b81ce3705b1511127) usbreset utility to accomplish that.

NOTE: The code is not written to be highly portable, it works with 2 of my usb-modems. However I think that it is easily hackable, so i think it is easy for anyone to adapt it to other hardware.
It was more important for me to keep it small and hackable (you get all these features in < 500 lines of python).

## Features

Sending and receiving SMS.

It uses my [MqHelper](https://github.com/NoUsername/MqHelper) library to publish the inbox to the [mosquitto](http://mosquitto.org/) messagebus and also listens for sms-send requests on that bus.

In addition to connecting to the mosquitto messagebus it runs a small internal webserver (using flask) so you can view your inbox (last 5 SMS) and send SMS via HTTP.

## How to run

	cd py
	# install python package dependencies if you haven't done so
	sudo pip install flask
    # probably needs to run as root for access to usb devices depending on your system
	sudo python smsSender.py

## Usage examples

How to send sms via mosquitto

    mosquitto_pub -t '/sms/outbox' -m '{"to":"6700","msg":"GUT"}'

How to send sms via curl

    curl --data "" "http://127.0.0.1:5353/sms/send?to=6700&msg=GUT"
