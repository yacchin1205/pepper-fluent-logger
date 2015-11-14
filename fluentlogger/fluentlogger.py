# -*- coding: utf-8 -*-
import sys
import qi
import random
import threading
import traceback
import socket
import time
import collections
import resource
from fluent import sender
from fluent import event
import dstat

PREF_DOMAIN = 'com.github.yacchin1205.fluentlogger'
DEFAULT_METRICS_INTERVAL = 30
MIN_METRICS_INTERVAL = 10
DEFAULT_DSTAT_PLUGINS = ['cpu', 'mem', 'load', 'disk', 'net', 'proc']

ACTUATORS = ["HeadPitch", "HeadYaw",
             "RShoulderRoll", "RShoulderPitch", "RElbowYaw", "RElbowRoll",
             "RWristYaw", "RHand",
             "LShoulderRoll", "LShoulderPitch", "LElbowYaw", "LElbowRoll",
             "LWristYaw", "LHand",
             "HipPitch", "HipRoll", "KneePitch",
             "WheelFL", "WheelFR", "WheelB"]


class FluentLoggerService:
    def __init__(self, session):
        self.session = session
        self.lock = threading.RLock()
        self.running = False
        self.logListener = None
        self.handlerId = None
        self.metricsInterval = DEFAULT_METRICS_INTERVAL
        self.logLevel = {'Fatal': 1, 'Error': 2, 'Warning': 3, 'Info': 4,
                         'Verbose': 5, 'Debug': 6}
        self.robotName = None
        self.memory = None
        self.retryCount = 0
        self.dstatPlugins = None

    def start(self):
        self._tryToStart()

    def stop(self):
        self.retryCount = 0
        self._stopWatchingLogs()
        self.dstatPlugins = None
        with self.lock:
            if self.running:
                self.sendEvent('service', {'status': 'stopped'})
            self.running = False

    def setForwarder(self, host, port):
        prefManager = self.session.service('ALPreferenceManager')
        prefManager.setValue(PREF_DOMAIN, 'host', host)
        prefManager.setValue(PREF_DOMAIN, 'port', str(port))
        self.start()

    def setWatchingLogs(self, enabled):
        value = 0
        if enabled:
            value = 1
        prefManager = self.session.service('ALPreferenceManager')
        prefManager.setValue(PREF_DOMAIN, 'qi_log', str(value))
        if enabled:
            self._startWatchingLogs()
        else:
            self._stopWatchingLogs()
        return True

    def setWatchingLogLevel(self, level):
        validLevels = sorted(self.logLevel.keys())
        if level not in validLevels:
            return False
        prefManager = self.session.service('ALPreferenceManager')
        prefManager.setValue(PREF_DOMAIN, 'qi_log_level', level)
        if self.logListener:
            self.logListener.setLevel(self.logLevel[level])
        else:
            self._startWatchingLogs()
        return True

    def onLogMessage(self, msg):
        try:
            self.sendEvent('log', msg)
        except:
            pass

    def _tryToStart(self):
        self.robotName = self._getRobotName()
        if self.robotName is None:
            self.retryCount += 1
            qi.async(self._tryToStart, delay=5 * 1000 * 1000 * self.retryCount)
            return
        with self.lock:
            if self.running:
                self.stop()
            host = self._get_pref('host')
            if host is not None:
                tag = self._get_pref('tag', 'pepper')
                sender.setup(tag, host=host,
                             port=int(self._get_pref('port', '24224')))
                self.running = True
                interval = self._get_pref('metrics_interval',
                                          str(DEFAULT_METRICS_INTERVAL))
                self.metricsInterval = max(int(interval), MIN_METRICS_INTERVAL)
                dstat.elapsed = self.metricsInterval
                self.dstatPlugins = None
                metrics_conf = {'interval_sec': self.metricsInterval}
                self.sendEvent('service', {'status': 'started',
                                           'config': metrics_conf,
                                           'retried': self.retryCount})
        self._startWatchingLogs()
        self._sendMetrics()

    def _startWatchingLogs(self):
        with self.lock:
            if int(self._get_pref('qi_log', '0')) != 0 and not self.handlerId:
                self.logListener = self.session.service('LogManager') \
                                       .createListener()
                logLevelStr = self._get_pref('qi_log_level', 'Info')
                self.logListener.setLevel(self.logLevel[logLevelStr])
                self.handlerId = self.logListener \
                                     .onLogMessage.connect(self.onLogMessage)

    def _stopWatchingLogs(self):
        with self.lock:
            if self.handlerId:
                self.logListener.onLogMessage.disconnect(self.handlerId)
                self.logListener = None
                self.handlerId = None

    def _sendLinuxMetrics(self):
        if self.dstatPlugins is None:
            try:
                dstat.op.full = True
                dstat.op.cpulist = ['all']
                dstat.cpunr = dstat.getcpunr()
                dstat.starttime = time.time()
                dstat.tick = dstat.ticks()
                dstat.update = 0
                dstat.pagesize = resource.getpagesize()
                self.dstatPlugins = []
                pluginNames = self._get_pref('dstat_plugins',
                                             ','.join(DEFAULT_DSTAT_PLUGINS))

                for pname in pluginNames.split(','):
                    try:
                        stat = getattr(dstat, 'dstat_' + pname)()
                        stat.check()
                        stat.prepare()
                        self.dstatPlugins.append((pname, stat))
                    except:
                        print('Failed to check %s: %s' % (pname,
                                                          sys.exc_info()[0]))
                        traceback.print_exc()

                for name, stat in self.dstatPlugins:
                    stat.extract()
            finally:
                dstat.update += self.metricsInterval
        else:
            try:
                for name, stat in self.dstatPlugins:
                    stat.extract()
                    if stat.nick:
                        vals = map(lambda name: get_dstat_values(stat.nick,
                                   stat.val[name]), stat.vars)
                    else:
                        vals = map(lambda name: stat.val[name], stat.vars)
                    self.sendEvent(name, dict(zip(stat.vars, vals)))
            finally:
                dstat.update += self.metricsInterval

    def _sendBodyMetrics(self):
        if self.memory is None:
            self.memory = self.session.service('ALMemory')
        battery_charge = self.memory.getData('BatteryChargeChanged')
        self.sendEvent('battery', {'charge': battery_charge})

        values = {}
        for actuator in ACTUATORS:
            key = 'Device/SubDeviceList/%s/Temperature/Sensor/Value' % actuator
            try:
                values[actuator.lower()] = int(self.memory.getData(key))
            except:
                print('Failed to get %s: %s' % (key, sys.exc_info()[0]))
                traceback.print_exc()
        self.sendEvent('temperature', values)

    def _sendAmbientMetrics(self):
        peopleList = self.memory.getData('PeoplePerception/PeopleList')
        visible = 0
        facedetected = 0
        distances = []
        for p in peopleList:
            key = 'PeoplePerception/Person/%d/' % p
            try:
                if self.memory.getData(key + 'IsVisible'):
                    visible += 1
                if self.memory.getData(key + 'IsFaceDetected'):
                    facedetected += 1
                distances.append(self.memory.getData(key + 'Distance'))
            except:
                print('Failed to get %s: %s' % (key, sys.exc_info()[0]))
                traceback.print_exc()

        min_distance = min(distances) if len(distances) > 0 else None
        max_distance = max(distances) if len(distances) > 0 else None
        self.sendEvent('people', {'all': len(peopleList),
                                  'visible': visible,
                                  'facedetected': facedetected,
                                  'min_distance': min_distance,
                                  'max_distance': max_distance})

    def _sendMetrics(self):
        if not self.running:
            return
        try:
            self._sendLinuxMetrics()
        except:
            print('Failed to send linux metrics: %s' % sys.exc_info()[0])
            traceback.print_exc()
        try:
            self._sendBodyMetrics()
        except:
            print('Failed to send body metrics: %s' % sys.exc_info()[0])
            traceback.print_exc()
        try:
            self._sendAmbientMetrics()
        except:
            print('Failed to send ambient metrics: %s' % sys.exc_info()[0])
            traceback.print_exc()

        qi.async(self._sendMetrics, delay=self.metricsInterval * 1000 * 1000)

    def _get_pref(self, name, default_value=None):
        prefManager = self.session.service('ALPreferenceManager')
        value = prefManager.getValue(PREF_DOMAIN, name)
        if value is None:
            return default_value
        else:
            return value

    def sendEvent(self, tag, msg):
        if self.robotName is not None:
            msg['robot'] = self.robotName
            event.Event(tag, msg)

    def _getRobotName(self):
        realNotVirtual = False
        try:
            ALMemory = self.session.service('ALMemory')
            ALMemory.getData("DCM/Time")
            if ALMemory.getData("DCM/Simulation") != 1:
                realNotVirtual = True
            else:
                import os
                realNotVirtual = os.path.exists("/home/nao")
        except:
            pass

        if realNotVirtual:
            return socket.gethostname()
        else:
            return None


def get_dstat_values(nick, val):
    if isinstance(val, collections.Iterable):
        return dict(zip(nick, val))
    else:
        return val


def main():
    app = qi.Application()
    app.start()
    session = app.session
    myService = FluentLoggerService(session)
    session.registerService("FluentLoggerService", myService)
    myService.start()
    app.run()

if __name__ == "__main__":
    main()
