#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function
import subprocess
import re

def getModemUsbInfo():
	output = subprocess.check_output('lsusb', stderr=subprocess.STDOUT)
	lines = output.split('\n')
	for l in lines:
		if "Huawei" in l:
			return l
	return None

def getModemBusAndDeviceId():
	modemInfo = getModemUsbInfo()
	if modemInfo == None:
		return None
	m = re.search('Bus (\w+) Device (\w+).*', modemInfo)
	# returns list bus-id at idx0, device-id at idx1
	return m.groups()

def resetModem():
	busAndDev = getModemBusAndDeviceId()
	if busAndDev == None:
		print(u"no modem found")
		return
	output = subprocess.check_output(('usbreset', busAndDev[0], busAndDev[1]), stderr=subprocess.STDOUT)
	print(u"reset done, output:")
	print(output)

if __name__=='__main__':
	resetModem()