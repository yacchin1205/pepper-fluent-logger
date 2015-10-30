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
    
    def stop(self):
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