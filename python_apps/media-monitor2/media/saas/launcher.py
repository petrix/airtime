import os, sys
import logging
import logging.config

import media.monitor.pure          as mmp

from media.monitor.exceptions    import FailedToObtainLocale, FailedToSetLocale
from media.monitor.log           import get_logger, setup_logging
from std_err_override            import LogWriter
from media.saas.thread           import InstanceThread, user, apc
from media.monitor.log           import Loggable
from media.monitor.exceptions    import CouldNotCreateIndexFile
from media.monitor.toucher       import ToucherThread
from media.monitor.airtime       import AirtimeNotifier, AirtimeMessageReceiver
from media.monitor.watchersyncer import WatchSyncer
from media.monitor.eventdrainer  import EventDrainer
from media.monitor.manager       import Manager
from media.saas.airtimeinstance  import AirtimeInstance

class MM2(InstanceThread, Loggable):

    def index_create(self, index_create_attempt=False):
        config = user().mm_config
        if not index_create_attempt:
            if not os.path.exists(config['index_path']):
                self.logger.info("Attempting to create index file:...")
                try:
                    with open(config['index_path'], 'w') as f: f.write(" ")
                except Exception as e:
                    self.logger.info("Failed to create index file with exception: %s" \
                             % str(e))
                else:
                    self.logger.info("Created index file, reloading configuration:")
                    self.index_create(index_create_attempt=True)
        else:
            self.logger.info("Already tried to create index. Will not try again ")

        if not os.path.exists(config['index_path']):
            raise CouldNotCreateIndexFile(config['index_path'])

    def run(self):
        self.index_create()
        manager = Manager()
        apiclient = apc()
        config = user().mm_config
        watch_syncer = WatchSyncer(signal='watch',
                                   chunking_number=config['chunking_number'],
                                   timeout=config['request_max_wait'])
        airtime_receiver = AirtimeMessageReceiver(config,manager)
        airtime_notifier = AirtimeNotifier(config, airtime_receiver)

        store = apiclient.setup_media_monitor()

        self.logger.info(
                "Initing with the following airtime response:%s" % str(store))

        airtime_receiver.change_storage({ 'directory':store[u'stor'] })

        for watch_dir in store[u'watched_dirs']:
            if not os.path.exists(watch_dir):
                # Create the watch_directory here
                try: os.makedirs(watch_dir)
                except Exception:
                    self.logger.error("Could not create watch directory: '%s' \
                            (given from the database)." % watch_dir)
            if os.path.exists(watch_dir):
                airtime_receiver.new_watch({ 'directory':watch_dir }, restart=True)
            else: self.logger.info("Failed to add watch on %s" % str(watch_dir))

        ed = EventDrainer(airtime_notifier.connection,
                interval=float(config['rmq_event_wait']))

        # Launch the toucher that updates the last time when the script was
        # ran every n seconds.
        # TODO : verify that this does not interfere with bootstrapping because the
        # toucher thread might update the last_ran variable too fast
        tt = ToucherThread(path=config['index_path'],
                           interval=int(config['touch_interval']))

        apiclient.register_component('media-monitor')

        manager.loop()

def launch_instance(name, root, global_cfg, apc_cfg):
    cfg = {
        'api_client'    : apc_cfg,
        'media_monitor' : global_cfg,
    }
    ai = AirtimeInstance(name, root, cfg)
    MM2(ai).start()

def setup_global(log):
    """ setup unicode and other stuff """
    log.info("Attempting to set the locale...")
    try: mmp.configure_locale(mmp.get_system_locale())
    except FailedToSetLocale as e:
        log.info("Failed to set the locale...")
        sys.exit(1)
    except FailedToObtainLocale as e:
        log.info("Failed to obtain the locale form the default path: \
                '/etc/default/locale'")
        sys.exit(1)
    except Exception as e:
        log.info("Failed to set the locale for unknown reason. \
                Logging exception.")
        log.info(str(e))

def setup_logger(log_config, logpath):
    logging.config.fileConfig(log_config)
    #need to wait for Python 2.7 for this..
    #logging.captureWarnings(True)
    logger = logging.getLogger()
    LogWriter.override_std_err(logger)
    logfile = unicode(logpath)
    setup_logging(logfile)
    log = get_logger()
    return log
