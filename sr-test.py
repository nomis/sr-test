#!/usr/bin/env python3
from datetime import datetime
import argparse
import fcntl
import glob
import multiprocessing as mp
import os

CDROMEJECT = 0x5309
CDROMCLOSETRAY = 0x5319

def init(lock_):
	global lock
	lock = lock_

def uprint(*args, **kwargs):
	now = datetime.now()
	print(now, *args, **kwargs)

def lprint(*args, **kwargs):
	now = datetime.now()
	with lock:
		print(now, *args, **kwargs)

def device_info(device):
	uprint(f"** {device}")

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

	drivers = "/".join(drivers)
	uprint(f"-- {drivers}")

def tray_eject(device):
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
	uprint(f"== Tray ejected on {name}, {ret} ({stop - start})")

def tray_close(device):
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
	uprint(f"== Tray closed on {name}, {ret} ({stop - start})")

def is_usb(device):
	return "/usb" in device

if __name__ == "__main__":
	mp.set_start_method("forkserver")
	lock = mp.Lock()

	devices = list(sorted([os.path.realpath(sr) for sr in glob.glob("/sys/class/block/sr*")]))

	parser = argparse.ArgumentParser(description="sr tester")
	parser.add_argument("-e", "--eject", action="store_true", help="Eject all non-USB drives")
	parser.add_argument("-u", "--eject-usb", action="store_true", help="Eject all USB drives")
	parser.add_argument("-c", "--close", action="store_true", help="Close all non-USB drive trays")
	parser.add_argument("-t", "--close-usb", action="store_true", help="Close all USB drive trays")

	args = parser.parse_args()

	with mp.Pool(initializer=init, initargs=(lock,), processes=len(devices)) as pool:
		uprint("** Devices:")
		for device in devices:
			device_info(device)
		uprint()

		if args.eject or args.eject_usb:
			pool.map(tray_eject, list(filter(lambda device: (args.eject and not is_usb(device)) or (args.eject_usb and is_usb(device)), devices)))

		if args.close or args.close_usb:
			pool.map(tray_close, list(filter(lambda device: (args.close and not is_usb(device)) or (args.close_usb and is_usb(device)), devices)))
