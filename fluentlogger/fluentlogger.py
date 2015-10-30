# -*- coding: utf-8 -*-
import sys
import qi
import random
import threading
from fluent import sender
from fluent import event

PREF_DOMAIN = 'com.github.yacchin1205.fluentlogger'

class FluentLoggerService:
    def __init__(self, session):
        self.session = session
        self.lock = threading.RLock()
        self.running = False
        self.logListener = None
        self.handlerId = None
        self.logLevel = {'Fatal': 1, 'Error': 2, 'Warning': 3, 'Info': 4,
                         'Verbose': 5, 'Debug': 6}
        
    def start(self):
        with self.lock:
            if self.running:
                self.stop()
            host = self._get_pref('host')
            if host is not None:
                tag = self._get_pref('tag', 'pepper')
                sender.setup(tag, host=host,
                             port=int(self._get_pref('port', '24224')))
                event.Event('service', {
                    'status': 'started'
                })
                self.running = True
        self._startWatchingLogs()
    
    def stop(self):
        self._stopWatchingLogs()
        with self.lock:
            if self.running:
                event.Event('service', {
                    'status': 'stopped'
                })
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
            event.Event('log', msg)
        except:
            pass
        
    def _startWatchingLogs(self):
        with self.lock:
            if int(self._get_pref('qi_log', '0')) != 0 and not self.handlerId:
                self.logListener = self.session.service('LogManager').createListener()
                self.logListener.setLevel(self.logLevel[self._get_pref('qi_log_level', 'Info')])
                self.handlerId = self.logListener.onLogMessage.connect(self.onLogMessage)

    def _stopWatchingLogs(self):
        with self.lock:
            if self.handlerId:
                self.logListener.onLogMessage.disconnect(self.handlerId)
                self.logListener = None
                self.handlerId = None
            
    def _get_pref(self, name, default_value=None):
        prefManager = self.session.service('ALPreferenceManager')
        value = prefManager.getValue(PREF_DOMAIN, name)
        if value is None:
            return default_value
        else:
            return value
    
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