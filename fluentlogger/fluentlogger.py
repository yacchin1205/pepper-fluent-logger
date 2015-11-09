# -*- coding: utf-8 -*-
import sys
import qi
import random
import threading
import traceback
import socket
from fluent import sender
from fluent import event
from linux_metrics import cpu_stat
from linux_metrics import cpu_stat
from linux_metrics import net_stat

PREF_DOMAIN = 'com.github.yacchin1205.fluentlogger'
DEFAULT_METRICS_INTERVAL = 30
MIN_METRICS_INTERVAL = 10
DURATION_CPUPERC = 1

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

    def start(self):
        self._tryToStart()

    def stop(self):
        self.retryCount = 0
        self._stopWatchingLogs()
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
                metrics_conf = {'interval_sec': self.metricsInterval}
                self.sendEvent('service', {'status': 'started',
                                           'config': metrics_conf})
                self.sendEvent('cpu_info', cpu_stat.cpu_info())
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
        cpu_percents = {}
        for k, v in cpu_stat.cpu_percents().items():
            cpu_percents['cpu_' + k] = v
        load_avg = cpu_stat.load_avg()
        assert(len(load_avg) == 3)
        file_desc = cpu_stat.file_desc()
        assert(len(file_desc) == 3)
        stats = cpu_percents.items()
        stats += zip(['load_1min', 'load_5min', 'load_15min'], load_avg)
        stats += {'procs_running': cpu_stat.procs_running(),
                  'procs_blocked': cpu_stat.procs_blocked()}.items()
        stats += zip(['filedesc_allocated', 'filedesc_allocated_free',
                      'filedesc_max'], file_desc)
        self.sendEvent('cpu', dict(stats))

        for nic in ['wlan0', 'eth0', 'usb0']:
            rx, tx = net_stat.rx_tx_bytes(nic)
            self.sendEvent('net', {'nic': nic, 'rx_bytes': rx, 'tx_bytes': tx})

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

        qi.async(self._sendMetrics,
                 delay=(self.metricsInterval - DURATION_CPUPERC) * 1000 * 1000)

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
