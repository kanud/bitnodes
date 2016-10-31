#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# export.py - Exports enumerated data for reachable nodes into a JSON file.
#
# Copyright (c) Addy Yeow Chin Heng <ayeowch@gmail.com>
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

"""
Exports enumerated data for reachable nodes into a JSON file.
"""

import json
import logging
import os
import redis
import sys
import time
from ConfigParser import ConfigParser

# Redis connection setup
REDIS_SOCKET = os.environ.get('REDIS_SOCKET', "/tmp/redis.sock")
REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD', None)
REDIS_CONN = redis.StrictRedis(unix_socket_path=REDIS_SOCKET,
                               password=REDIS_PASSWORD)

SETTINGS = {}


def get_row(node):
    """
    Returns enumerated row data from Redis for the specified node.
    """
    # address, port, version, user_agent, timestamp, services
    node = eval(node)
    address = node[0]
    port = node[1]
    services = node[-1]

    height = REDIS_CONN.get('height:{}-{}-{}'.format(address, port, services))
    if height is None:
        height = (0,)
    else:
        height = (int(height),)

    hostname = REDIS_CONN.hget('resolve:{}'.format(address), 'hostname')
    hostname = (hostname,)

    geoip = REDIS_CONN.hget('resolve:{}'.format(address), 'geoip')
    if geoip is None:
        # city, country, latitude, longitude, timezone, asn, org
        geoip = (None, None, 0.0, 0.0, None, None, None)
    else:
        geoip = eval(geoip)

    return node + height + hostname + geoip


def export_nodes(nodes, timestamp):
    """
    Merges enumerated data for the specified nodes and exports them into
    timestamp-prefixed JSON file.
    """
    rows = []
    start = time.time()
    for node in nodes:
        row = get_row(node)
        rows.append(row)
    end = time.time()
    elapsed = end - start
    logging.info("Elapsed: %d", elapsed)

    dump = os.path.join(SETTINGS['export_dir'], "{}.json".format(timestamp))
    open(dump, 'w').write(json.dumps(rows, encoding="latin-1"))
    logging.info("Wrote %s", dump)

def export_inv(ik, invmsgs):
    """
    Exports inv messages of blocks (type 2)
    """
    rows = []
    start = time.time()
    for im in invmsgs:
        rows.append(im)
    end = time.time()
    elapsed = end - start
    #logging.info("Elapsed: %d", elapsed)
    dump = os.path.join(SETTINGS['export_dir'], "{}.json".format(ik[6:] + '_' + ik[4]))
    open(dump, 'w').write(json.dumps(rows, encoding="latin-1"))
    #logging.info("Wrote %s", dump)


def init_settings(argv):
    """
    Populates SETTINGS with key-value pairs from configuration file.
    """
    conf = ConfigParser()
    conf.read(argv[1])
    SETTINGS['logfile'] = conf.get('export', 'logfile')
    SETTINGS['debug'] = conf.getboolean('export', 'debug')
    SETTINGS['export_dir'] = conf.get('export', 'export_dir')
    if not os.path.exists(SETTINGS['export_dir']):
        os.makedirs(SETTINGS['export_dir'])


def main(argv):
    if len(argv) < 2 or not os.path.exists(argv[1]):
        print("Usage: export.py [config]")
        return 1

    # Initialize global settings
    init_settings(argv)

    # Initialize logger
    loglevel = logging.INFO
    if SETTINGS['debug']:
        loglevel = logging.DEBUG

    logformat = ("%(asctime)s,%(msecs)05.1f %(levelname)s (%(funcName)s) "
                 "%(message)s")
    logging.basicConfig(level=loglevel,
                        format=logformat,
                        filename=SETTINGS['logfile'],
                        filemode='w')
    print("Writing output to {}, press CTRL+C to terminate..".format(
        SETTINGS['logfile']))

    pubsub = REDIS_CONN.pubsub()
    pubsub.subscribe('resolve')
    while True:
        msg = pubsub.get_message()
        if msg is None:
            time.sleep(0.001)  # 1 ms artificial intrinsic latency.
            continue
        # 'resolve' message is published by resolve.py after resolving hostname
        # and GeoIP data for all reachable nodes.
        if msg['channel'] == 'resolve' and msg['type'] == 'message':
            timestamp = int(msg['data'])  # From ping.py's 'snapshot' message
            logging.info("Timestamp: %d", timestamp)
            nodes = REDIS_CONN.smembers('opendata')
            logging.info("Nodes: %d", len(nodes))
            export_nodes(nodes, timestamp)

            # export inv messages
            ik_iter = REDIS_CONN.scan_iter(match='inv')
            ik_count = 0
            for ik in ik_iter:
                ik_count += 1
                invmsgs = REDIS_CONN.zrange(ik, 0, -1)
                export_inv(ik, invmsgs)

            logging.info("Inv keys: %d", ik_count)

            REDIS_CONN.publish('export', timestamp)

    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
