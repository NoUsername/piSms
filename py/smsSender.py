#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function
import sys
import random
import json
import os
import re
import time
import traceback
from messaging.sms import SmsDeliver
from messaging.sms import SmsSubmit
from Queue import Queue
import flask

app = flask.Flask(__name__)

if not app.debug:
	import logging 
	handler = logging.FileHandler('sms.log')
	handler.setLevel(logging.WARNING)
	app.logger.addHandler(handler)

FROM_KEY = "from"
TO_KEY = "to"
MSG_KEY = "msg"
STATUS_KEY = "status"
WHEN_KEY = "when"
SMS_COUNT = "smsCount"

Q_SMSINBOX = "smsInbox"

DAILY_MAX = 2

STORAGE_SELECT = 'AT+CPMS="SM","SM","SM"'


def __textResponse(data):
	return (data, 200, {'Content-Type': 'text/plain; charset=utf-8'})

@app.route("/sms/outbox", methods=["POST"])
@app.route("/sms/send", methods=["POST"])
def send():
	to = flask.request.args.get(TO_KEY, '')
	msg = flask.request.args.get(MSG_KEY, '')
	# also allow "text" param
	msg = flask.request.args.get("text", '') if msg == '' else msg
	if to == '' or msg == '':
		return __textResponse('"to" or "msg" argument missing or invalid!')
	cfg = flask.current_app.config
	count = cfg.get(SMS_COUNT, 0)
	if count >= DAILY_MAX:
		return __textResponse("ERROR: max daily sms reached")
	cfg[SMS_COUNT] = (count + 1)

	serialOut = cfg.get('serialOut', None)
	if serialOut != None:
		serialOut.put(json.dumps({TO_KEY: to, MSG_KEY: msg}))
		return __textResponse("sent")
	else:
		return __textResponse('no serial port queue')

@app.route("/sms/reset")
def reset():
	cfg = flask.current_app.config
	cfg[SMS_COUNT] = 0
	return __textResponse("reset done")

@app.route("/sms/in")
@app.route("/sms/inbox")
@app.route("/sms/received")
def received():
	pretty = flask.request.args.get('pretty', '') != ''
	try:
		serialIn = flask.current_app.config.get(Q_SMSINBOX, None)
		data = None
		nextData = serialIn.get(False) if not serialIn.empty() else None
		# get the newest data that's in the queue
		while nextData != None:
			data = nextData
			nextData = serialIn.get(False) if not serialIn.empty() else None
		if data != None:
			flask.current_app.config['lastSms'] = data
		else:
			data = flask.current_app.config.get('lastSms', '{}')
		if pretty:
			return __textResponse(json.dumps(json.loads(data), indent=2))
		else:
			return __textResponse(data)
	except:
		reason = traceback.format_exc()
		print(u"error occured:\n%s"%reason)
		return __textResponse("error")

def __openSerial(SERIALPORT):
	import serial
	ser = serial.Serial(port=SERIALPORT, baudrate=9600, timeout=0.5, writeTimeout=5)
	time.sleep(1)
	return ser

def __constructMsg(to, msg):
	pdu = SmsSubmit(to, msg).to_pdu()[0]
	result = 'ATZ\r' + \
			'AT+CMGF=0\r' + \
			STORAGE_SELECT + '\r' + \
			('AT+CMGS=%s\r'%pdu.length) + \
			pdu.pdu + chr(26)
	return result

def __readNextAck(ser, altAck=None):
	output = ''
	done = False
	print(u"waiting for ack")
	started = time.time()
	while not done:
		data = ser.readline()
		if data:
			output += data
			lines = re.split("\r[\n]", output)
			count = sum(l == 'OK' or l == 'ERROR' or l.startswith('+CMS ERROR') for l in lines)
			if altAck != None:
				count += altAck(lines)
			done = count > 0
		else:
			time.sleep(0.1)
		if time.time() - started > 10:
			raise Exception('could not read ack in time')
	print(u"acked by: '%s'"%output)

def __serSend(ser, data):
	print(u"writing: %s"%data)
	ser.write(bytearray(data, 'ASCII'))

def __readSms(ser):
	ser.flushInput()
	msgs = ['ATZ',
			'AT+CMGF=0',
			STORAGE_SELECT,		# select sim-card storage (required on some modems)
			'AT+CMGL=4']		# 4 is "ALL" (get read & unread) 
	for idx, msg in enumerate(msgs):
		__serSend(ser, "%s\r"%msg)
		time.sleep(0.1)
		if idx==2:
			ser.flushInput()
	time.sleep(2)
	output = ""
	done = False
	print(u"reading sms from device")
	started = time.time()
	while not done:
		output += ser.readline()
		print(u"read: %s"%output)
		lines = re.split("\r[\n]", output)
		done = lines.count("OK") + lines.count("ERROR") >= 1
		if time.time() - started > 20:
			raise Exception('could not read sms in time')
	ser.flushInput()

	lines = re.split("\r[\n]", output)
	msgs = []
	nextIsPdu = False
	smsIdx = 0
	for line in lines:
		if nextIsPdu:
			# print(u"parse pdu: %s"%line)
			sms = SmsDeliver(line)
			sms.smsIdx = smsIdx
			msgs.append(sms)
		if line.startswith("+CMGL"):
			nextIsPdu = True
			match = re.search("\+CMGL: (\d+),", line)
			smsIdx = match.group(1)
		else:
			nextIsPdu = False
			smsIdx = 0

	msgs = sorted(msgs, key=lambda x:x.date)

	for msg in msgs:
		print(u"received from %s msg:\n%s\n\n"%(unicode(msg.number), unicode(msg.text)))

	return msgs

def __deleteSms(ser, smsList):
	__serSend(ser, "ATZ\r")
	time.sleep(1)
	__serSend(ser, STORAGE_SELECT + '\r')
	__readNextAck(ser)
	for sms in smsList:
		__serSend(ser, "AT+CMGD=%s\r"%sms.smsIdx)
		__readNextAck(ser)
	ser.flushInput()

def __trimSmsInbox(ser, msgs, maxSize):
	deleteMe = []
	if len(msgs) > maxSize:
		for i in xrange(len(msgs) - maxSize):
			deleteMe.append(msgs[i])

	if len(deleteMe) > 0:
		print(u"deleting %s sms"%len(deleteMe))
		__deleteSms(ser, deleteMe)
	else:
		print(u"no sms to delete, only %s sms"%len(msgs))

def __toDict(msg):
	return {'idx':msg.smsIdx, FROM_KEY: msg.number, MSG_KEY: msg.text,
		WHEN_KEY: str(msg.date)}

def __serialLoop(smsInbox, serialOut, idleIn):
	ser = None
	serialLastClosed = time.time()
	serialLastReopened = time.time() - 120
	while True:
		time.sleep(0.2)
		while ser == None or not ser.isOpen():
			SERIALPORT = '/dev/ttyUsbModem'
			print("opening serial connection %s"%(ser == None))
			if time.time() - serialLastReopened < 60:
				print(u"reopening serial port for the second time in 1 minute, resetting modem")
				import resetModem
				resetModem.resetModem()
				print(u"modem reset done, giving time for modem reboot")
				time.sleep(30)
			serialLastReopened = time.time()
			try:
				ser = None
				ser = __openSerial(SERIALPORT)
				ser.flushInput()
			except:
				print("error writing, try reopening")
				time.sleep(0.5)
				try:
					if ser != None:
						ser.close()
					ser = None
				except:
					pass

		sendMe = None
		try:
			sendMe = serialOut.get(False)
		except:
			pass
		if sendMe != None:
			try:
				msg = json.loads(sendMe)
				encodedMsg = __constructMsg(msg.get(TO_KEY), msg.get(MSG_KEY))
				print(u"sending sms to %s"%msg.get(TO_KEY))
				ser.flushInput()
				parts = encodedMsg.split("\r")
				for idx, part in enumerate(parts):
					__serSend(ser, part+"\r")
					#if idx != len(parts):
					__readNextAck(ser, lambda x: len([a for a in x if a.startswith(">")]))
				ser.flush()
			except:
				print(u"error while writing: '%s' error: %s"%(sendMe, traceback.format_exc()))
				serialIn.put(json.dumps({STATUS_KEY:'error writing to serial %s'%(sys.exc_info()[0])}))
				ser = None
		else:
			# nothing to send
			if time.time() - serialLastClosed > 5 * 60:
				# more than 5 minutes since last serial re-open, force reopen serial
				# this is done to give modem a chance to reset
				serialLastClosed = time.time()
				try:
					ser.close()
					ser = None
					time.sleep(5)
				except:
					pass
			else:
				# check for incoming messages
				try:
					time.sleep(4)
					msgs = []
					msgs = __readSms(ser)
					if len(msgs) > 0:
						all = []
						for msg in msgs:
							msgDict = __toDict(msg)
							all.append(msgDict)
							idleIn.put(json.dumps(msgDict))
						smsInbox.put(json.dumps(all))
						# delte after successfully broadcasting
						# TODO: it's not certain that they have been broadcasted, they are just in the queue
						# __deleteSms(ser, msgs)
						__trimSmsInbox(ser, msgs, 5)
				except:
					reason = traceback.format_exc()
					print(u"error reading sms inbox:\n%s"%reason)
					ser = None

def idleBroadcaster(idleMsgs, serialOut):
	from MqHelper import MqHelper
	mq = MqHelper('sms')

	def callback(topic, msg):
		print('mq callback')
		serialOut.put(msg) 

	mq.subscribe('/sms/outbox', callback)
	while True:
		try:
			mq.loop()
		except:
			print(u"error in mq loop")
			time.sleep(2)
		time.sleep(0.2)
		msg = None
		try:
			msg = idleMsgs.get(False)
		except:
			pass
		if msg != None:
			mq.send('/sms/inbox', msg)

if __name__ == "__main__":
	import threading
	serialOut = Queue()
	smsInbox = Queue()
	serialIdleIn = Queue()
	def serialWorker():
		while True:
			try:
				__serialLoop(smsInbox, serialOut, serialIdleIn)
			except:
				reason = traceback.format_exc()
				print(u"fatal exception in serialLoop reason:\n%s"%reason)
				time.sleep(10)
	t = threading.Thread(target=serialWorker)
	t.daemon = True
	t.start()
	broadcaster = threading.Thread(target=idleBroadcaster, args=[serialIdleIn, serialOut])
	broadcaster.daemon = True
	broadcaster.start()

	if len(sys.argv) > 1:
		print(u"test mode, not starting http server")
		time.sleep(2)
		print(u"sending")
		# send balance-check SMS (for austrian provider 'HOT')
		serialOut.put(json.dumps({TO_KEY:"6700", MSG_KEY:"GUT"}))
		for i in range(100):
			try:
				msg = serialIdleIn.get(False)
				if msg != None:
					print(u"%s"%msg)
			except:
				pass
			time.sleep(2)
		sys.exit(0)

	app.config[SMS_COUNT] = 0
	app.config['serialOut'] = serialOut
	app.config[Q_SMSINBOX]  = smsInbox
	app.run(host="0.0.0.0", port=5353) # 5353 somehow looks like smsm

# example commandline how to send sms via mosquitto:
#    mosquitto_pub -t '/sms/outbox' -m '{"to":"6700","msg":"GUT"}'
# example of how to send sms via curl
#    curl --data "" "http://127.0.0.1:5353/sms/send?to=6700&msg=GUT"
