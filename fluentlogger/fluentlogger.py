# -*- coding: utf-8 -*-
import sys
import qi
import random
import threading
from fluent import sender
from fluent import event

class FluentLoggerService:
    def __init__(self):
        self.lock = threading.RLock()
        self.running = False
        
    def start(self):
        with self.lock:
            if self.running:
                self.stop()
            sender.setup('pepper', host='192.168.10.119', port=24224)
            event.Event('service', {
                'status': 'started'
            })
    
    def stop(self):
        with self.lock:
            if self.running:
                event.Event('service', {
                    'status': 'stopped'
                })
            self.running = False    
    
def main():
    app = qi.Application()
    app.start()
    session = app.session
    myService = FluentLoggerService()
    session.registerService("FluentLoggerService", myService)
    myService.start()
    app.run()

if __name__ == "__main__":
    main()