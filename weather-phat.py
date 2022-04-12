#!/usr/bin/env python
# -*- coding: utf-8 -*-

import glob
import json
import os
import time
from os.path import exists
from dateutil import parser
from datetime import datetime, timedelta

from dotenv import load_dotenv
from font_fredoka_one import FredokaOne
from inky.auto import auto
from PIL import Image, ImageDraw, ImageFont

import requests
import geocoder
from bs4 import BeautifulSoup

# Get the current path
PATH = os.path.dirname(__file__)

# Set up the display
inky_display = auto(ask_user=True, verbose=True)

if inky_display.resolution not in ((212, 104), (250, 122)):
    w, h = inky_display.resolution
    raise RuntimeError("This example does not support {}x{}".format(w, h))

inky_display.set_border(inky_display.BLACK)

# Load config from environment or .env
load_dotenv()
CITY = os.getenv("CITY", default="London")
COUNTRYCODE = os.getenv("COUNTRYCODE", default="GB")
WARNING_TEMP = float(os.getenv("WARNING_TEMP", default="25.0"))
ADMIRALTY_API_KEY = os.getenv("ADMIRALTY_API_KEY", default="")
ADMIRALTY_API_STATION_ID = os.getenv("ADMIRALTY_API_STATION_ID", default="0113")
ADMIRALTY_API_HIGH_TIDE_CORRECTION = int(os.getenv("ADMIRALTY_API_HIGH_TIDE_CORRECTION", default="0"))
ADMIRALTY_API_LOW_TIDE_CORRECTION = int(os.getenv("ADMIRALTY_API_LOW_TIDE_CORRECTION", default="0"))


# Convert a city name and country code to latitude and longitude
def get_coords(address):
    g = geocoder.arcgis(address)
    coords = g.latlng
    return coords


def get_tides():
    results = []

    if ADMIRALTY_API_KEY == "":
        return results

    # See https://admiraltyapi.portal.azure-api.net/docs/services/uk-tidal-api/operations/TidalEvents_GetTidalEvents?
    res = requests.get(
        f"https://admiraltyapi.azure-api.net/uktidalapi/api/V1/Stations/{ADMIRALTY_API_STATION_ID}/TidalEvents?duration=2",
        headers={"Ocp-Apim-Subscription-Key": ADMIRALTY_API_KEY})

    if res.status_code != 200:
        return results

    current_time = datetime.now()
    data = json.loads(res.content.decode())
    correction = {"H": ADMIRALTY_API_HIGH_TIDE_CORRECTION, "L": ADMIRALTY_API_LOW_TIDE_CORRECTION}
    for entry in data:
        prefix = entry["EventType"][0]  # Extract H or L as prefix for tide time
        dt = parser.parse(entry["DateTime"]) + timedelta(minutes=correction[prefix])
        if dt > current_time:
            results.append("{}{}".format(prefix, dt.strftime("%H:%M")))

    return results


# Query Dark Sky (https://darksky.net/) to scrape current weather data
def get_weather(address, use_cache=False):
    coords = get_coords(address)
    weather = {}

    if not use_cache:
        try:
            os.unlink("cache.html")
        except FileNotFoundError as e:
            pass

    if not exists("cache.html"):
        res = requests.get("https://darksky.net/forecast/{}/uk212/en".format(",".join([str(c) for c in coords])))
        if res.status_code != 200:
            return weather
        f = open("cache.html", "wb")
        f.write(res.content)
        f.close()

    f = open("cache.html", "r")
    content = f.read()
    f.close()

    soup = BeautifulSoup(content, "lxml")
    curr = soup.find_all("span", "currently")
    weather["summary"] = curr[0].img["alt"].split()[0]
    weather["temperature"] = int(curr[0].find("span", "summary").text.split()[0][:-1])
    wind = soup.find_all("div", "wind")
    speed = wind[0].find("span", "num")
    unit = wind[0].find("span", "unit")
    direction = wind[0].find("span", "direction")
    weather["wind"] = "{} {} {}".format(int(speed.text), unit.text, direction["title"])
    return weather


def create_mask(source, mask=(inky_display.WHITE, inky_display.BLACK, inky_display.RED)):
    """Create a transparency mask.

    Takes a paletized source image and converts it into a mask
    permitting all the colours supported by Inky pHAT (0, 1, 2)
    or an optional list of allowed colours.

    :param mask: Optional list of Inky pHAT colours to allow.

    """
    mask_image = Image.new("1", source.size)
    w, h = source.size
    for x in range(w):
        for y in range(h):
            p = source.getpixel((x, y))
            if p in mask:
                mask_image.putpixel((x, y), 255)

    return mask_image


# Dictionaries to store our icons and icon masks in
icons = {}
masks = {}

# Get the weather data for the given location
location_string = "{city}, {countrycode}".format(city=CITY, countrycode=COUNTRYCODE)
weather = get_weather(location_string)
tides = get_tides()

# This maps the weather summary from Dark Sky
# to the appropriate weather icons
icon_map = {
    "snow": ["snow", "sleet"],
    "rain": ["rain"],
    "cloud": ["fog", "cloudy", "partly-cloudy-day", "partly-cloudy-night"],
    "sun": ["clear-day", "clear-night"],
    "storm": [],
    "wind": ["wind"]
}

# Placeholder variables
wind = ""
temperature = 0
weather_icon = None

if weather:
    temperature = weather["temperature"]
    wind = weather["wind"]
    summary = weather["summary"]

    for icon in icon_map:
        if summary in icon_map[icon]:
            weather_icon = icon
            break

else:
    print("Warning, no weather information found!")

# Create a new canvas to draw on
# img = Image.open(os.path.join(PATH, "resources/backdrop.png")).resize(inky_display.resolution)
img = Image.new("P", (inky_display.WIDTH, inky_display.HEIGHT), inky_display.BLACK)
draw = ImageDraw.Draw(img)

# Load our icon files and generate masks
for icon in glob.glob(os.path.join(PATH, "resources/icon-*.png")):
    icon_name = icon.split("icon-")[1].replace(".png", "")
    icon_image = Image.open(icon)
    icons[icon_name] = icon_image
    masks[icon_name] = create_mask(icon_image)

# Load the FredokaOne font
font = ImageFont.truetype(FredokaOne, 21)

# Draw lines to frame the weather data
draw.line((69, 36, 69, 81))  # Vertical line
draw.line((31, 35, 184, 35))  # Horizontal top line
draw.line((69, 58, 174, 58))  # Horizontal middle line
draw.line((169, 58, 169, 58), 2)  # Red seaweed pixel :D
draw.line((31, 81, 184, 81))  # Horizontal top line

# Write text with weather values to the canvas
datetime = time.strftime("%d/%m %H:%M")

draw.text((42, 12), datetime, inky_display.WHITE, font=font)

draw.text((72, 34), u"{}°".format(temperature), inky_display.WHITE if temperature < WARNING_TEMP else inky_display.RED,
          font=font)

draw.text((72, 58), "{}".format(wind), inky_display.WHITE, font=font)

if tides:
    draw.text((32, 80), " / ".join(tides[:2]), inky_display.WHITE, font=font)

# Draw the current weather icon over the backdrop
if weather_icon is not None:
    img.paste(icons[weather_icon], (28, 36), masks[weather_icon])

else:
    draw.text((28, 36), "?", inky_display.RED, font=font)

# Display the weather data on Inky pHAT
inky_display.set_image(img)
inky_display.show()
