#!/usr/bin/env python3
import argparse
import logging
import signal
import fsevents
import paramiko
from sys import argv,exit
from time import sleep
from os.path import expanduser,normpath,dirname,isfile,islink
from fsevents import Observer, Stream
from paramiko.ssh_exception import SSHException
from re import compile as regexp

class sftpwatch:
    def __init__(
        self,
        ignore = [
            regexp(r'.*\.git.*'),
            regexp(r'.*\.DS_Store$')
        ],
        mapping = [],
        host = None,
        user = None,
        password = None,
        rootdir = None
        
    ):
        self.ignore = ignore
        self.PATH_MAPPING = mapping
        self.host = host
        self.user = user
        self.password = password
        self.root = rootdir
        self.observer = None
        self.stream = None
        self.sf = None
        self.connected = False
        self.exit = False
        try:
            self.connect();
        except Exception as e:
            logging.critical("SSH Could not connect!")
            logging.critical(str(e))
            exit(1)
    
    def connect(self):
        self.sf = self.getsftp(args.host, args.user, args.password)
        
    def watch(self):
        self.observer = Observer()
        self.observer.start()
        self.stream = Stream(self.file_event_callback, self.root, file_events=True)
        self.observer.schedule(self.stream)
        

    def ssh_connect(self, hostname, username, password):
        """Connect to SSH server and return (authenticated) transport socket"""
        host_keys = paramiko.util.load_host_keys(expanduser('~/.ssh/known_hosts'))
        if hostname in host_keys:
            hostkeytype = host_keys[hostname].keys()[0]
            hostkey = host_keys[hostname][hostkeytype]
            logging.debug('Using host key of type %s' % hostkeytype)
        else:
            logging.critical("Host key not found")
            exit(0)
        
        t = paramiko.Transport((hostname, 22))
        t.set_keepalive(30)
        t.connect(hostkey, username, password)
        return t

    def getsftp(self, hostname, username, password):
        """Return a ready-to-roll paramiko sftp object"""
        t = self.ssh_connect(hostname, username, password)
        return paramiko.SFTPClient.from_transport(t)

    def transfer_file(self, localpath, remotepath):
        """Transfer file over sftp"""
        with self.sf.open(remotepath, 'wb') as destination:
            with open(localpath, 'rb') as source:
                total = 0
                while True:
                    data = source.read(8192)
                    if not data:
                        return total
                    destination.write(data)
                    total += len(data)

    def file_event_callback(self, event):
        """Respond to file events"""
        
        
        # Make sure we have sftp connectivity
        while not self.exit:
            try:
                assert not self.sf == None
                self.sf.stat("/")
                break
            except (OSError, AssertionError) as e:
                logging.warning("Attempting to connect...")
                try:
                    self.connect()
                    break
                except Exception as ee:
                    logging.warning("Could not Connect.")
                    logging.error("Error was: %s" % str(ee))
                    logging.warning("Trying again in 5 seconds...")
                    sleep(5)
        
        if self.exit:
            return
        
        # check ignored
        for expr in self.ignore:
            if not expr.match(event.name) == None:
                return
    
        # Determine file path relative to our root
        filePath = event.name.replace(self.root, "")
        logging.debug("Path from basedir: %s" % filePath)
    
        # Apply directory mapping
        for mapping in self.PATH_MAPPING:
            localMapPath,remoteMapPath = mapping
            if filePath[0:len(localMapPath)]==localMapPath:
                logging.debug("Using mapping: %s" % (str(mapping)))
                filePath = remoteMapPath + "/" + filePath[len(localMapPath):]
                break
    
        filePath = normpath(filePath)
    
        # Ensure path starts with /
        if filePath[0] != "/":
           filePath = "/" + filePath 

        if event.mask & (fsevents.IN_MODIFY|fsevents.IN_CREATE|fsevents.IN_MOVED_TO):
            logging.debug("\nFile was modified: %s" % event.name)
        
            logging.debug("Remote path: %s" % filePath)
        
            # Ensure directory exists
            path_dirs = dirname(filePath).split("/")
        
            for i in range(1,len(path_dirs)):
                pathSegment = "/".join(path_dirs[0:i+1])
                logging.debug("stat %s" % pathSegment)
                try:
                    self.sf.stat(pathSegment)
                except IOError as e:
                    logging.info("Creating %s" % pathSegment)
                    self.sf.mkdir(pathSegment)
        
            # If file, upload it
            if isfile(event.name) or islink(event.name):
                tries = 0
                while True:
                    try:
                        bytesSent = self.transfer_file(event.name, filePath)
                        break
                    except IOError as ioe:
                        logging.error("Unable to upload file: %s" % str(ioe))
                        # reconnect to SSH on error
                        #sf.close()
                        #sf = getsftp(args.host, args.user, args.password)
                    tries+=1
                    sleep(0.5)
                    if tries > 5:
                        return False
            
                logging.info("%s: sent %s KB to %s" % (event.name, max(1, int(bytesSent/1024)), filePath))
            else:
                logging.info("Not a file: %s" % event.name)
    
        if event.mask & (fsevents.IN_MOVED_FROM|fsevents.IN_DELETE):
            logging.info("removing %s" % filePath)
            # Just delete it
            try:
                self.sf.remove(filePath)
            except:
                # Silently fail so we don't delete unexpected stuff
                pass
    
        """
        We can respond to: 
    
        done IN_MOVED_FROM - path is old file path
        done IN_MOVED_TO - path is new file path 
        done IN_MODIFY - file was edited 
        done IN_CREATE - file was created
        done IN_DELETE - file was deleted
             IN_ATTRIB - attributes modified - ignore for now
        """
        #self.sf.close()

    def signal_handler(self, signal, frame):
        logging.info('Cleaning up....')
        self.exit = True
        self.observer.unschedule(self.stream)
        self.observer.stop()


if __name__ == "__main__":
    from os import getcwd
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(module)s %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    parser = argparse.ArgumentParser(description="Watch a directory for file changes and sync them to an sftp server")
    parser.add_argument("root", nargs='?',  default=getcwd(), action="store",  help="Root directory to watch")
    parser.add_argument('-m', '--map',                        action='append', help="Directory mapping such as \"server/cms:/var/www/drupal\"")
    parser.add_argument('-u', '--user',     required=True,    action='store',  help="SSH username")
    parser.add_argument('-p', '--password', required=True,    action='store',  help="SSH password")
    parser.add_argument('-s', '--host',     required=True,    action='store',  help="SSH server")
    args = parser.parse_args()
    
    if args.map==None:
        logging.critical("At least one --map is required.")
        exit(1)
    
    path_maps = []
    
    for mapping in args.map:
        path_maps.append(mapping.split(":"))
    
    
    pywatch = sftpwatch(mapping=path_maps, host=args.host, user=args.user, password=args.password, rootdir=args.root)
    
    signal.signal(signal.SIGINT, pywatch.signal_handler)
    
    logging.info("watching %s" % args.root)
    
    pywatch.watch()
