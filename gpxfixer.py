# python3
import numpy as np
from bs4 import BeautifulSoup as bs
from bs4 import element as bs_element
import argparse
import os
import re
import sys
import dateutil.parser
from dateutil.tz import UTC
from datetime import datetime, timedelta


class TrackPoint:
    MIN_RATE = 1.5

    def __init__(self, pt):
        self.pt = pt
        self.lat = float(pt["lat"])
        self.lon = float(pt["lon"])
        self.time = dateutil.parser.parse(pt.time.string)
        # self.time.replace(tzinfo=UTC)
        self.ele = float(pt.ele.string)
        self.elapsed = 0
        self.nelapsed = 0
        self.distance = 0
        self.accumulated_distance = 0
        self.ndistance = 0
        self.since_last = 0
        try:
            track_pt_extensions = [
                ext for ext in pt.extensions.contents if isinstance(ext, bs_element.Tag)
            ]
            self.extensions = [
                t
                for t in track_pt_extensions[0].contents
                if isinstance(t, bs_element.Tag)
            ]
        except:
            self.extensions = []

    def adjust_time(self, origin, last, total_seconds):
        self.elapsed = self.time - origin.time
        self.nelapsed = self.elapsed.total_seconds() / total_seconds
        self.since_last = (self.time - last.time).total_seconds()

    def adjust_distance(self, last):
        # https://www.movable-type.co.uk/scripts/latlong.html
        R = 6371e3  # metres
        theta1 = last.lat * np.pi / 180
        theta2 = self.lat * np.pi / 180
        delta_theta = (self.lat - last.lat) * np.pi / 180
        delta_lambda = (self.lon - last.lon) * np.pi / 180
        a = np.sin(delta_theta / 2) * np.sin(delta_theta / 2) + np.cos(theta1) * np.cos(
            theta2
        ) * np.sin(delta_lambda / 2) * np.sin(delta_lambda / 2)
        c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
        d = R * c
        self.distance = d

    def set_ndistance(self, last, total_distance):
        self.accumulated_distance = self.distance + last.accumulated_distance
        self.ndistance = self.accumulated_distance / total_distance

    def add_extensions(self, soup, polyfit):
        new_extensions = soup.new_tag("extensions", "")
        new_track_point_extensions = soup.new_tag("ns3:TrackPointExtension", "")
        new_extensions.append(new_track_point_extensions)
        for (ext, poly) in polyfit.items():
            new_value = poly(self.ndistance)
            if ext[:4] != "ns3:":
                ext = f"ns3:{ext}"
            if ext[4:] == "atemp":
                new_value = round(new_value, 1)
            else:
                new_value = int(round(new_value))
            new_ext = soup.new_tag(ext)
            new_ext.string = str(new_value)
            new_track_point_extensions.append(new_ext)
        try:
            self.pt.extensions.replace_with(new_extensions)
        except:
            self.pt.append(new_extensions)

    def append_fit_values(self, values):
        for ext in self.extensions:
            if not ext.name in values:
                values[ext.name] = {"x": [], "y": []}
            values[ext.name]["x"].append(self.nelapsed)
            values[ext.name]["y"].append(float(ext.string))

    def fix_time(self, origin_time, total_seconds):
        nelapsed = total_seconds * self.ndistance
        self.time = origin_time + timedelta(seconds=nelapsed)
        ms = self.time.strftime("%f")[:3]
        time_string = self.time.strftime("%Y-%m-%dT%H:%M:%S")
        self.pt.time.string = f"{time_string}.{ms}Z"

    def calc_still_time(self):
        rate = self.distance / self.since_last if self.since_last > 0 else 0
        if rate < TrackPoint.MIN_RATE:
            return self.since_last
        return 0


class GpxFile:
    def __init__(self, filename):
        self.filename = filename
        with open(filename) as fp:
            self.soup = bs(fp, "xml")
            self.pts = [
                TrackPoint(c)
                for c in self.soup.trk.trkseg.children
                if isinstance(c, bs_element.Tag)
            ]
            self.total_seconds = (self.pts[-1].time - self.pts[0].time).total_seconds()
            self.origin = self.pts[0]
            for (i, pt) in enumerate(self.pts[1:]):
                pt.adjust_distance(self.pts[i])
                pt.adjust_time(self.origin, self.pts[i], self.total_seconds)
            self.total_distance = sum([pt.distance for pt in self.pts])
            for (i, pt) in enumerate(self.pts[1:]):
                pt.set_ndistance(self.pts[i], self.total_distance)
            # get polyvalues
            self.values = {}
            for pt in self.pts:
                pt.append_fit_values(self.values)
            # make polyfit functions
            self.polyfit = {}
            for (ext, points) in self.values.items():
                pfit = np.polyfit(np.array(points["x"]), np.array(points["y"]), 3)
                self.polyfit[ext] = np.poly1d(pfit)
            # stopped time
            self.total_still_time = sum([pt.calc_still_time() for pt in self.pts])

    def add_extensions(self, original):
        for pt in self.pts:
            pt.add_extensions(self.soup, original.polyfit)

    def fix_time(self, original):
        for pt in self.pts:
            pt.fix_time(
                original.start_time(),
                original.total_seconds - original.total_still_time,
            )

    def replace_gps(self, replacement):
        self.soup.trk.trkseg.replace_with(replacement.soup.trk.trkseg)

    def __str__(self):
        return str(self.soup)

    def start_time(self):
        return self.pts[0].time

    def pretty(self):
        return self.soup.prettify()


def main():
    parser = argparse.ArgumentParser(description="Replace GPS in GPX")
    parser.add_argument(
        "--gpx", "-g", type=str, required=True, help="original GPX file"
    )
    parser.add_argument(
        "--replace", "-r", type=str, required=True, help="replacement GPX file"
    )
    parser.add_argument(
        "--output", "-o", type=str, default=None, help="replacement GPX file"
    )
    parser.add_argument(
        "--pretty", "-p", action="store_true", default=False, help="pretty print"
    )
    parsed = parser.parse_args()
    if parsed.output:
        sys.stdout = open(parsed.output, "w")
    original = GpxFile(parsed.gpx)
    replacement = GpxFile(parsed.replace)
    replacement.add_extensions(original)
    replacement.fix_time(original)
    original.replace_gps(replacement)
    if parsed.pretty:
        print(original.pretty())
    else:
        print(original)

    return 0


if __name__ == "__main__":
    sys.exit(main())
