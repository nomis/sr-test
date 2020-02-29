#!/usr/bin/env python3
# sr-test - Test concurrent operations on Linux sr devices
# Copyright 2020  Simon Arlott
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from datetime import datetime, timedelta
import argparse
import fcntl
import glob
import multiprocessing as mp
import pickle
import os
import sys
import time

CDROMEJECT = 0x5309
CDROMCLOSETRAY = 0x5319
CDROM_LOCKDOOR = 0x5329

def init(lock_):
	global lock
	lock = lock_

def uprint(*args, **kwargs):
	now = datetime.now()
	print(now, *args, **kwargs)
	sys.stdout.flush()

def lprint(*args, **kwargs):
	now = datetime.now()
	with lock:
		print(now, *args, **kwargs)
		sys.stdout.flush()

def device_drivers(device):
	parts = device.split("/")
	drivers = []
	for n in range(4, len(parts) + 1):
		base = os.path.join("/", *parts[0:n])

		driver = None
		try:
			driver = os.path.basename(os.readlink(os.path.join(base, "driver")))
		except FileNotFoundError:
			continue

		vendor = None
		product = None
		try:
			with open(os.path.join(base, "vendor"), "r") as f:
				vendor = f.read().strip().replace("0x", "")
			with open(os.path.join(base, "device"), "r") as f:
				product = f.read().strip().replace("0x", "")
		except FileNotFoundError:
			pass

		try:
			with open(os.path.join(base, "idVendor"), "r") as f:
				vendor = f.read().strip().replace("0x", "")
			with open(os.path.join(base, "idProduct"), "r") as f:
				product = f.read().strip().replace("0x", "")
		except FileNotFoundError:
			pass

		if vendor and product:
			driver = f"{driver}[{vendor}:{product}]"

		drivers.append(driver)

	return drivers

def device_info(device):
	uprint(f"** {device}")

	drivers = "/".join(device_drivers(device))
	uprint(f"-- {drivers}")

def format_td(td):
	if td < timedelta(0):
		return "-" + str(-td)
	else:
		return "+" + str(td)

def tray_eject(data):
	(device, timings) = data

	name = "/dev/" + device.split("/")[-1]
	uprint(f"== Tray ejecting on {name}")
	start = datetime.now()

	uprint(f"-- Opening {name}")
	fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK)
	uprint(f"-- Opened {name}")
	try:
		ret = fcntl.ioctl(fd, CDROMEJECT, 1)
	except OSError as e:
		ret = e
	uprint(f"-- Closing {name}")
	os.close(fd)
	uprint(f"-- Closed {name}")

	stop = datetime.now()
	reference = format_td((stop - start) - timings["eject"]) if timings else ""
	uprint(f"== Tray ejected on {name}, 0x{ret:x} ({stop - start}) {reference} {device_type(device)}")
	return stop - start

def tray_close(data):
	(device, timings) = data

	name = "/dev/" + device.split("/")[-1]
	uprint(f"== Tray closing on {name}")
	start = datetime.now()

	uprint(f"-- Opening {name}")
	fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK)
	uprint(f"-- Opened {name}")
	try:
		ret = fcntl.ioctl(fd, CDROMCLOSETRAY, 0)
	except OSError as e:
		ret = e
	uprint(f"-- Closing {name}")
	os.close(fd)
	uprint(f"-- Closed {name}")

	stop = datetime.now()
	reference = format_td((stop - start) - timings["close"]) if timings else ""
	uprint(f"== Tray closed on {name}, 0x{ret:x} ({stop - start}) {reference} {device_type(device)}")
	return stop - start

def door_lock(device):
	name = "/dev/" + device.split("/")[-1]
	uprint(f"== Door locking on {name}")
	start = datetime.now()

	uprint(f"-- Opening {name}")
	fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK)
	uprint(f"-- Opened {name}")
	try:
		ret = fcntl.ioctl(fd, CDROM_LOCKDOOR, 1)
	except OSError as e:
		ret = e
	uprint(f"-- Closing {name}")
	os.close(fd)
	uprint(f"-- Closed {name}")

	stop = datetime.now()
	uprint(f"== Door locked on {name}, 0x{ret:x} ({stop - start})")

def door_unlock(device):
	name = "/dev/" + device.split("/")[-1]
	uprint(f"== Door unlocking on {name}")
	start = datetime.now()

	uprint(f"-- Opening {name}")
	fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK)
	uprint(f"-- Opened {name}")
	try:
		ret = fcntl.ioctl(fd, CDROM_LOCKDOOR, 0)
	except OSError as e:
		ret = e
	uprint(f"-- Closing {name}")
	os.close(fd)
	uprint(f"-- Closed {name}")

	stop = datetime.now()
	uprint(f"== Door unlocked on {name}, 0x{ret:x} ({stop - start})")

def is_usb(device):
	return "/usb" in device

def is_pata(device, drivers=None):
	if drivers is None:
		drivers = device_drivers(device)
	for driver in drivers:
		if driver.startswith("pata"):
			return True
	return False

def is_sata(device, drivers=None):
	if drivers is None:
		drivers = device_drivers(device)
	for driver in drivers:
		if driver.startswith("sata"):
			return True
	return False

"""Order by pata (most likely to block other accesses), then sata, then usb (non-motorised tray eject)."""
def device_sort_key(device, drivers=None):
	if is_usb(device):
		return ("usb", device)

	if drivers is None:
		drivers = device_drivers(device)
	if is_pata(device, drivers):
		return ("pata", device)
	if is_sata(device, drivers):
		return ("sata", device)

	return (None, device)

def device_type(device):
	drivers = device_drivers(device)

	if is_pata(device, drivers):
		ata = ""
		parts = device.split("/")
		for n in range(4, len(parts)):
			if parts[n].startswith("ata"):
				ata = " " + parts[n]
		return device_sort_key(device, drivers)[0] + ata + (" slave" if ":1:0/block" in device else " master")
	else:
		return device_sort_key(device, drivers)[0]

def reference_timings(devices):
	timings = {}
	for device in devices:
		timings[device] = { "eject": tray_eject((device, None)) }
		time.sleep(5)
		timings[device]["close"] = tray_close((device, None))
		time.sleep(5)

	return timings

if __name__ == "__main__":
	mp.set_start_method("forkserver")
	lock = mp.Lock()

	devices = list(sorted([os.path.realpath(sr) for sr in glob.glob("/sys/class/block/sr*")], key=device_sort_key))

	parser = argparse.ArgumentParser(description="sr tester")
	parser.add_argument("-r", "--reference", action="store_true", help="Obtain referencing timings for tray eject/close")
	parser.add_argument("-s", "--sequential", action="store_true", help="Run sequentially")
	parser.add_argument("-e", "--eject", action="store_true", help="Eject all non-USB drives")
	parser.add_argument("-u", "--eject-usb", action="store_true", help="Eject all USB drives")
	parser.add_argument("-c", "--close", action="store_true", help="Close all non-USB drive trays")
	parser.add_argument("-t", "--close-usb", action="store_true", help="Close all USB drive trays")
	parser.add_argument("-L", "--lock", action="store_true", help="Lock all drive doors")
	parser.add_argument("-U", "--unlock", action="store_true", help="Unlock all drive doors")

	args = parser.parse_args()

	with mp.Pool(initializer=init, initargs=(lock,), processes=1 if args.sequential else len(devices)) as pool:
		uprint("** Devices:")
		for device in devices:
			device_info(device)
		uprint()

		if args.unlock:
			pool.map(door_unlock, devices)

		try:
			with open("timings.pickle", "rb") as f:
				timings = pickle.load(f)
		except FileNotFoundError:
			timings = {}

		if args.reference:
			timings = reference_timings(filter(lambda device: not is_usb(device), devices))

			with open("timings.pickle", "wb") as f:
				pickle.dump(timings, f)

		if args.eject or args.eject_usb:
			pool.map(tray_eject, [(device, timings.get(device)) for device in list(filter(lambda device: (args.eject and not is_usb(device)) or (args.eject_usb and is_usb(device)), devices))])

		if args.close or args.close_usb:
			pool.map(tray_close, [(device, timings.get(device)) for device in list(filter(lambda device: (args.close and not is_usb(device)) or (args.close_usb and is_usb(device)), devices))])

		if args.lock:
			pool.map(door_lock, devices)
