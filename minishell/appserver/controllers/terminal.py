######################################
# derives heavily from https://splunkbase.splunk.com/app/1607/ kudos!
# Dominique Vocat, 2017
######################################

import os
import cherrypy
import logging
import logging.handlers
import json
import subprocess
import shlex

import splunk, splunk.util
import splunk.appserver.mrsparkle.controllers as controllers
from splunk.appserver.mrsparkle.lib.decorators import expose_page
from splunk.appserver.mrsparkle.lib.routes import route
from splunk.appserver.mrsparkle.lib import jsonresponse, util, cached

def setup_logger(level):
    logger = logging.getLogger('minishell')
    logger.propagate = False # Prevent the log messages from being duplicated in the python.log file
    logger.setLevel(level)

    file_handler = logging.handlers.RotatingFileHandler(os.path.join(os.environ.get("SPLUNK_HOME"), 'var', 'log', 'splunk', 'minishell.log'), maxBytes=25000000, backupCount=5)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)

    return logger

logger = setup_logger(logging.INFO)

class TerminalController(controllers.BaseController):


    def render_template(self, template_path, template_args = {}):
        template_args['appList'] = self.get_app_manifest()
        return super(TerminalController, self).render_template(template_path, template_args)
    def get_app_manifest(self):
        output = cached.getEntities('apps/local', search=['disabled=false','visible=true'], count=-1)
        return output 
        
    @expose_page(must_login=True, methods=['GET'])
    @route('/', methods=['GET'])
    def view(self, **kwargs):
        
        app = cherrypy.request.path_info.split('/')[3]

        return self.render_template('/%s:/templates/terminal.html' % app, dict(app=app))

    
    @expose_page(must_login=True, methods=['POST'])
    @route('/', methods=['POST'])
    def process(self, **kwargs):
        user = cherrypy.session['user']['name']
        #logger.info('setting up controller')
        #logger.info('try to import libraries')
        import sys
        sys.path.append(os.path.join(os.environ['SPLUNK_HOME'],'etc','apps','minishell','appserver','controllers')) #build local path and add it to the python path so we can load modules, hack!
        #logger.info('path='+str(sys.path))
        
        command = kwargs.get('command')
        PWD = kwargs.get('pwd')
        #logger.info('from js stack PWD='+PWD)
        splitCommand = shlex.split(command) if os.name == 'posix' else command.split(' ')
        #logger.info('splitCommand='+str(splitCommand))
        isRestartCommand = False
        if not command:
            error = "No command"
            return self.render_json(dict(success=False, payload=error, pwd=PWD))
        
        #logger.info('user='+str(user)+ ' command='+str(command))
        #logger.info('import sultan')
        from sultan.api import Sultan
        s = Sultan()
        
        #merge all comand line parameters
        parameters = ""
        for param in splitCommand[1:]:
            parameters += ' ' + param
            
        #logger.info('user session info: '+json.dumps(cherrypy.session['user']))
            
        try:
            if splitCommand[0] == "help":
                    logger.info('user asked for help')
                    payload = """you can run splunk with command line parameters regardles of current working dir,
run git on the current working dir and list files. Does not support chaining!
Commands:
 ls     lists files, see http://linuxcommand.org/man_pages/ls1.html for more
 pwd    to see what the current working dir is
 cd     specify the fully qualified working dir like cd /var/log etc
 git    see https://git-scm.com/documentation for more
 tail   -f won't work
 head   yeah
 cat    again yeah.
 clear  clear the screen
 wget   see https://www.gnu.org/software/wget/manual/wget.html
 grep   see https://www.gnu.org/software/grep/manual/grep.html for more
 find   see https://www.gnu.org/software/findutils/manual/html_mono/find.html for more
 
 notice: if the command takes too long you will run into timeouts"""
            elif splitCommand[0] == "git":            
                with Sultan.load(cwd=PWD, sudo=False) as s:
                    returnvalue = s.git(parameters).run()
                    payload = '\n'.join(returnvalue)
            elif splitCommand[0] == "cat":            
                with Sultan.load(cwd=PWD, sudo=False) as s:
                    returnvalue = s.cat(parameters).run()
                    payload = '\n'.join(returnvalue)
            elif splitCommand[0] == "head":
                with Sultan.load(cwd=PWD, sudo=False) as s:
                    returnvalue = s.head(parameters).run()
                    payload = '\n'.join(returnvalue)
            elif splitCommand[0] == "wget":
                with Sultan.load(cwd=PWD, sudo=False) as s:
                    returnvalue = s.wget(parameters).run()
                    payload = '\n'.join(returnvalue)
            elif splitCommand[0] == "grep":
                with Sultan.load(cwd=PWD, sudo=False) as s:
                    returnvalue = s.grep(parameters).run()
                    payload = '\n'.join(returnvalue)
            elif splitCommand[0] == "tail":            
                if " -f " in command:
                    payload = "tail -f won't work"
                    return self.render_json(dict(success=False, payload=payload, pwd=PWD))
                with Sultan.load(cwd=PWD, sudo=False) as s:
                    returnvalue = s.tail(parameters).run()
                    payload = '\n'.join(returnvalue)
            elif splitCommand[0] == "find":            
                with Sultan.load(cwd=PWD, sudo=False) as s:
                    returnvalue = s.find(parameters).run()
                    payload = '\n'.join(returnvalue)
            elif splitCommand[0] == "ls":            
                with Sultan.load(cwd=PWD, sudo=False) as s:
                    returnvalue = s.ls(parameters).run()
                    payload = '\n'.join(returnvalue)
            elif splitCommand[0] == "splunk":            
                with Sultan.load( sudo=False) as s:
                    os.environ['SPLUNK_TOK'] = str(cherrypy.session['sessionKey'])
                    splunkCommand = command[7:]
                    logger.info('load command splunk with parameters=' + splunkCommand)
                    returnvalue = s.splunk(splunkCommand).run()
                    del os.environ['SPLUNK_TOK']
                    payload = '\n'.join(returnvalue)
                    #logger.info('user='+ user + ' in workingdir=' + PWD + ' command=' +splitCommand[0] + ' arguments=' + parameters)
            elif splitCommand[0] == "pwd":            
                try:
                    payload = PWD
                    #payload = 'pwd: ' + cherrypy.session['user']['pwd'] #pwd
                except KeyError, e:
                    cherrypy.session['user']['pwd'] = os.environ['SPLUNK_HOME']
                    logger.info('no pwd was set, default to splunk_home')
                    payload = 'pwd: ' + cherrypy.session['user']['pwd'] #pwd
                    return self.render_json(dict(success=False, payload=payload, pwd=PWD))
                logger.info('we showed the pwd')
                #logger.info('user session info: '+json.dumps(cherrypy.session['user']))
            elif splitCommand[0] == "cd":
                #logger.info('trying to set path')
                tmpPWD = os.path.abspath(os.path.join(PWD, splitCommand[1]))
                #logger.info('path we check if it exists... ' + tmpPWD)
                if os.path.isdir(tmpPWD):
                    #logger.info('path exists')
                    PWD = tmpPWD
                    payload = "set current working dir to " + PWD
                else:
                    logger.info('path does not exist, fail')
                    payload = 'does not seem to be a directory that exists...'
                    return self.render_json(dict(success=False, payload=payload, pwd=PWD))
            else:
                payload = 'command ' + splitCommand[0] + ' is not supported or misspelled, try "help" for more...'
                return self.render_json(dict(success=False, payload=payload, pwd=PWD))
            logger.info('user="'+ user + '" in workingdir="' + PWD + '" command="' +splitCommand[0] + '" commandline="' + command + '"')

        except Exception, e:
            import traceback
            stack =  traceback.format_exc()
            #splunk.Intersplunk.generateErrorResults("Error : Traceback: '%s'. %s" % (e, stack))
            logger.info('exception='+str(e)+' stacktrace='+str(stack))
            return self.render_json(dict(success=False, payload=str(e), pwd=PWD))
        
        return self.render_json(dict(success=True, payload=str(payload), pwd=PWD))
    