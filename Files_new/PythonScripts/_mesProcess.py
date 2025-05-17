from string import punctuation
import time
import datetime
from collections import OrderedDict
from typing import get_type_hints
import schedule
import pprint
import json
import paho.mqtt.client as mqtt
import os
import subprocess
import _mesScreen
import re
from mysql.connector import connect, Error
import sys
import os


'''Manufacturing Execution Sysytem (MES)'''

class mesProcess:
    def __init__(self):
        # self.quit is only changed by self.systemStatusCallback
            # init self.quit as False
            # if self.quit changes to True, the script and screen will terminate
        self.quit = False

        # attribute modifiable by the process itself.
        # when at the end of a process, execution ends
        self.isThisProcessComplete = False

        self.runID, self.user, self.runType, self.operationName = \
            _mesScreen.unpackSTY()
        
        # this will be used to get the list of tasks
        self.processName = \
            self.operationName.split('_')[0]

        # May crash with processA_1of20
        # Consider splitting by '_' then by 'of'
        self.operationName = self.operationName[-4:]

        self.processFileLocation = \
            '_mesProcessFiles/' + self.user+'/'+self.processName+'.txt'

        # Connect to the database
        self.db_connect()

        self.initMQTT()
        
        # Arg parsing for debugging mode:
        # If debugging mode is enabled, copy sys.stdout content to .txt file in ./debug
        if len(sys.argv) > 1:
            if '-d' in sys.argv:
                debugFilename = './debug/' + self.runID + '~' + self.processName + '~' + self.operationName + '.txt'
                sys.stdout = open(debugFilename, 'w')
                print('Now printing to file!')
        
        print('Just before task dict')
        self.createTaskDict()
        # self.publishoperationTasks()
        schedule.every(0.5).seconds.do(self.checkCurrentTask)
        #schedule.every(1).seconds.do(self.publishoperationTasks)
        self.loopProcess()

    def db_connect(self):
        select_process_query = 'SELECT * FROM process_handler'

        '''
        IMPORTANT:
        You may need to run a SQL command in order to connect to the mySQL database from a detached screen. The command is:

        ALTER USER 'yourusername'@'localhost' IDENTIFIED WITH mysql_native_password BY 'yourpassword';

        Source: https://stackoverflow.com/questions/49194719/authentication-plugin-caching-sha2-password-cannot-be-loaded
        '''

        # Move this to a config file
        self.connection = connect(
            host="localhost",
            user='root',
            password='buADML@2021',
            database="bumes",
        )
                
        # Why three cursors 0,0
        self.cursor = self.connection.cursor()
        self.cursor1 = self.connection.cursor(buffered = True)
        self.cursor2 = self.connection.cursor()
        # self.cursor.execute(select_process_query)
        # result = self.cursor.fetchall()
        # for row in result:
        #     self.mqttClient.publish('debug', str(row))

    def createTaskDict(self):
        with open(self.processFileLocation, 'r') as processFile:
            taskNumber = 1 #starting task

            # process_table query string for populating tasks
            insert_new_tasks_process_query = "INSERT INTO process_handler (process_name, task_name, notes, command, task_complete, operation_name) VALUES ('" +\
                self.processName + "', "

            for task in processFile:
                    task = task.strip() #remove leading and trailing whitespace
                    if task == '\n' or task =='':
                        # print('NOT TASK (Empty Line):',repr(task)) ### FOR DEBUGGING
                        pass # exclude empty lines, move to the next iteration
                    elif task.startswith('//'):
                        # print('NOT TASK (Comment):',repr(task)) ### FOR DEBUGGING
                        pass # exclude comments
                    else:
                        try:
                            task = task.split('//')[0] # remove inline comments
                        except: 
                            pass # no inline comments
                        task = task.strip() # remove leading or trailing whitespace left by the comment
                        # print('TASK:',repr(task)) ### FOR DEBUGGING
                        if task.find('readyForAssembly') != -1:
                            assemblyArguments = re.split('\(|\)',task)[-2]
                            assemblyArguments = assemblyArguments.replace("'",'').replace("‘",'').replace("’",'').replace("‛",'').split(',')

                            # New db code:
                            self.readyForAssembly(taskNumber, assemblyArguments, insert_new_tasks_process_query)
                        else:
                            # New db code:
                            command = [task.replace('\n', '')][0]
                            command = [task.replace("'", "''").replace("‘","''").replace("’","''").replace("‛","''")][0]

                            newQuery = insert_new_tasks_process_query + "'task_" + str(taskNumber) + "', '', '" + command + "', False, '" + \
                                self.operationName + "')"

                            self.cursor.execute(newQuery)
                            self.connection.commit()

                        taskNumber += 1

            newQuery = insert_new_tasks_process_query + "'task_" + str(taskNumber) + "', '', 'endProcess()', False, '" + self.operationName + \
                "')"

            self.cursor.execute(newQuery)
            self.connection.commit()

        # Check if has startupTasksComplete()
        # Prepend it if not
        # Was erroring because it was not checking for this specific process
        select_command_process_query = "SELECT id FROM process_handler WHERE command = 'startupTasksComplete()' AND process_name = '" + self.processName + "' LIMIT 1"
        self.cursor.execute(select_command_process_query)
        result = self.cursor.fetchall()
        self.connection.commit()

        '''
        WARNING: If the database has been wiped and IDs are reset to incrementing from 1, the first process you run may have its first task
        overwritten by the following insertion IF it is missing a startupTasksComplete() command. This is because since IDs are permanent even 
        after clearing records, we add the startupTasksComplete() command in with ID of 1 to ensure it is run FIRST. But if the database has been 
        wiped, it will overrite the first task of the first process/operation being run. You can simply run a quick-sim to increment the DB IDs enough
        to start another process with no issues.

        UPDATE: Starting startupTasksComplete() with an ID of 1 caused an issue when running more than one process without that command.
        Every process tried to take the ID spot of 1 but since it was taken by the first process that ran, they would not be able to add it
        so they never marked them as finished. Hence the next operations never ran from backend. This is now fixed by setting the startupTasksComplete() for
        that process to the current lowest ID minus 1. Even though processes running after the first one will technically have a lower ID, it won't matter for
        task execution since they only take their own tasks by process name, hence the startupTasksComplete() is still their first task to execute.
        '''

        if result == []:

            get_lowest_id_query = "SELECT Min(id) FROM process_handler"
            self.cursor.execute(get_lowest_id_query)
            result = self.cursor.fetchall()
            lowestID = result[0][0]
            newID = lowestID - 1
            self.connection.commit()

            print('StartupTasksComplete not found, lowest ID is ' + str(lowestID) + ', new ID is ' + str(newID))

            newQuery = "INSERT INTO process_handler (id, process_name, task_name, notes, command, task_complete, operation_name) VALUES (" + str(newID) + ", '" +\
                self.processName + "', " + "'task_0', '', 'startupTasksComplete()', False, '" + self.operationName + "')"

            self.cursor.execute(newQuery)
            self.connection.commit()

        # self.writeProcessReport()

    def readyForAssembly(self, taskNumber, assemblyArguments, insert_new_tasks_process_query):
        primaryProcess = assemblyArguments[0]
        secondaryProcess = assemblyArguments[1]
        assemblyStep = assemblyArguments[2]

        if assemblyStep == 'initializeAssembly':
            newQuery = insert_new_tasks_process_query + "'task_" + str(taskNumber) + "', 'readyForAssemblyMacro-initializeAssembly', 'resourceSeize(''" + \
                primaryProcess + "'')', False, '" + self.operationName + "')"

            self.cursor.execute(newQuery)
            self.connection.commit()

        elif assemblyStep == 'startAssembly':
            newQuery = insert_new_tasks_process_query + "'task_" + str(taskNumber) + ".1', 'readyForAssemblyMacro-startAssembly', 'resourceRelease(''" + \
                primaryProcess + "'')', False, '" + self.operationName + "')"

            self.cursor.execute(newQuery)
            self.connection.commit()

            newQuery = insert_new_tasks_process_query + "'task_" + str(taskNumber) + ".2', 'readyForAssemblyMacro-startAssembly', 'resourceSeize(''" + \
                secondaryProcess + "'')', False, '" + self.operationName + "')"

            self.cursor.execute(newQuery)
            self.connection.commit()

        elif assemblyStep == 'finishAssembly':
            newQuery = insert_new_tasks_process_query + "'task_" + str(taskNumber) + ".1', 'readyForAssemblyMacro-finishAssembly', 'resourceRelease(''" + \
                secondaryProcess + "'')', False, '" + self.operationName + "')"

            self.cursor.execute(newQuery)
            self.connection.commit()

            newQuery = insert_new_tasks_process_query + "'task_" + str(taskNumber) + ".2', 'readyForAssemblyMacro-finishAssembly', 'resourceSeize(''" + \
                primaryProcess + "'')', False, '" + self.operationName + "')"

            self.cursor.execute(newQuery)
            self.connection.commit()

            newQuery = insert_new_tasks_process_query + "'task_" + str(taskNumber) + ".3', 'readyForAssemblyMacro-finishAssembly', 'resourceRelease(''" + \
                primaryProcess + "'')', False, '" + self.operationName + "')"

            self.cursor.execute(newQuery)
            self.connection.commit()

    def initMQTT(self):
        self.mqttClient = mqtt.Client()
        self.mqttClient.on_connect = self.onConnect

        # Invoke MQTT callback self.outcomeSeize when an MQTT message arrives with the specified topic
        # self.mqttClient.message_callback_add('system/resources', self.getResources)

        self.mqttClient.message_callback_add(
            'resourceHandler/response/resourceSeize/' + self.processName + '/#', \
            self.outcomeSeize)
        
        self.mqttClient.message_callback_add(
            'system/status', \
            self.systemStatusCallback)
       
        self.mqttClient.message_callback_add(
            'urHandler/outcome/#', \
            self.outcomeUrDashboard)
       
        self.mqttClient.message_callback_add(
            'cncHandler/outcome/#', \
            self.outcomeCncRun)
        
        self.mqttClient.message_callback_add(
            'visionHandler/outcome/#', \
            self.outcomeVisionInspection)
       
        self.mqttClient.connect('localhost', 1883)

    def onConnect(self, client, userdata, flags, rc):        
        self.mqttClient.subscribe('system/#')
        
        self.mqttClient.subscribe('urHandler/outcome/'+self.processName+'/#')

        self.mqttClient.subscribe('resourceHandler/response/resourceSeize/' + self.processName + '/#')
        
        # FIX MQTT TOPICS FOR PROCESS NAME
        self.mqttClient.subscribe('cncHandler/outcome/'+self.operationName+'/#')
        # FIX MQTT TOPICS FOR PROCESS NAME
        self.mqttClient.subscribe('visionHandler/outcome/'+self.operationName+'/#')

    def flagDashboard(self):
        self.mqttClient.publish('dashboardHandler/updateTasks', 'none')

    # Publishes tasks list for the Dashboard Handler
    # CHANGE TO DB
    def publishoperationTasks(self):
        # tasks/axelWasHere.txt/axelWasHere_1of2 << TOPIC
        # Message is the operationTasks directory with the complete, running, or finished info
        self.mqttClient.publish(
                        'tasks/' + \
                        self.processName + '/' + \
                        str(self.operationName), \
                        json.dumps(self.operationTasks, indent=4))

    def checkCurrentTask(self):
        select_tasks_process_query = "SELECT * FROM process_handler WHERE process_name = '" +\
            self.processName + "' ORDER BY id"
        self.cursor1.execute(select_tasks_process_query)

        for row in self.cursor1:
            task = row[3]
            id = str(row[0])
            isTaskExecuting = row[7]

            select_command_process_query = "SELECT command FROM process_handler WHERE id = " + id + " LIMIT 1"

            self.cursor2.execute(select_command_process_query)
            command = self.cursor2.fetchall()[0][0]
            rawCommand = command

            # break the command into a list.  First index is function name.  Second index is arguments
            # Ex. command = ['self.resourceSeize','Rosie)']
            command = command.split('(')

            # Generate additional task argument 
            mqttArgument = "('" + id + "/" + task + "/" + self.operationName + "',"

            # insert the additional argument and join the string back together
            # ex. command = ['self.resourceSeize','task_1','Rosie)']
            command.insert(1, mqttArgument)

            # join the list back into a single string
            # Ex. command = 'self.resourceSeize(processA_1of2/task_3,Rosie)'
            command = ''.join(command)
                
            if isTaskExecuting == False:
                update_task_process_query = "UPDATE process_handler SET task_executing = True, start_time = '" + \
                    str(time.time()) + "' WHERE id = " + id

                self.cursor2.execute(update_task_process_query)
                self.connection.commit()
                self.flagDashboard()
                    
                # this message and topic appear on the fmc overview page (index.hmtl)
                    # Not used for any actual process execution.
                if 'endProcess' not in command:
                    self.mqttClient.publish(
                        'process/' + \
                        self.processName + '/' + \
                        self.operationName + '/' + \
                        task, \
                        rawCommand + \

                        '/Waiting to Execute')
                else:
                    self.mqttClient.publish(
                        'process/' + \
                        self.processName + '/' + \
                        self.operationName + '/' + \
                        task, \
                        rawCommand)


                # Execute the command from a string
                # print('COMMAND',command)
                exec('self.'+command)

                # stop the for loop from iterating through additional process steps
                break

            elif self.isTaskComplete(id) == False and isTaskExecuting == True: # If the task has not completed but already started:
                # print(self.isTaskComplete(id))
                self.flagDashboard()

                start_time = self.getStartTime(id)
                elapsedTime = round(time.time() - float(start_time))

                elapsedTime = 'Executing, Elapsed Time ' + str(elapsedTime) + ' seconds'

                # Waiting timestamp, for visualization on index.html. 
                    # Not used for any actual process execution.
                self.mqttClient.publish(
                    'process/' + \
                    self.processName + '/' + \
                    str(self.operationName) + '/' + \
                    str(task), \
                    rawCommand+'/'+elapsedTime)

                # execute resourceSeize commands again if they fail:
                if 'resourceSeize' in command:
                    exec('self.'+command)

                break

            elif self.isTaskComplete(id):
                # Task is complete, move on to check next task status
                pass

    def isTaskComplete(self, id):
        self.connection.commit()
        select_process_query = "SELECT task_complete FROM process_handler WHERE id = " + \
            id + " LIMIT 1"

        self.cursor.execute(select_process_query)
        result = self.cursor.fetchall()
        # print('ID: ', id)
        # print('task_complete: ', result[0][0])
        return result[0][0]     # in order to return boolean value, index first into list, then tuple

    def isTaskExecuting(self, id):
        select_task_executing_process_query = "SELECT task_executing FROM process_handler WHERE id = " + \
            id + " LIMIT 1"
        self.cursor.execute(select_task_executing_process_query)
        result = self.cursor.fetchall()
        return result[0][0]

    def getStartTime(self, id):
        select_start_time_process_query = "SELECT start_time FROM process_handler WHERE id = " + \
            id + " LIMIT 1"
        self.cursor.execute(select_start_time_process_query)
        result = self.cursor.fetchall()
        return result[0][0]

    def isSeized(self, resource):
        select_isSeized_resource_query = "SELECT isSeized FROM resource_handler WHERE name = '" + \
            resource + "' LIMIT 1"

        self.cursor.execute(select_isSeized_resource_query)
        result = self.cursor.fetchall()
        
        return result[0][0]

    # this command is generated within self.checkCurrentTask
    def resourceSeize(self, mqttTopic, resource, conveyorArg=None):
        processInfo = mqttTopic.split('/')
        task = processInfo[1]
        taskID = processInfo[0]

        # self.mqttClient.publish('debug', task[1])
        outcomeTopic = 'resourceHandler/response/resourceSeize/' + \
            self.processName + '/' + \
            task + '/' + \
            resource + '/GRANTED'

        # Check resource table to see if the selected resource is a Conveyor Station
        select_type_resource_query = "SELECT type FROM resource_handler WHERE name = '" + \
            resource + "' LIMIT 1"

        self.cursor.execute(select_type_resource_query)
        result = self.cursor.fetchall()
        
        if self.isSeized(resource) == 0:
            # Update resource table seized and usedBy field for currently selected resource
            update_isSeized_usedBy_resource_query = "UPDATE resource_handler SET isSeized = True, usedBy = '" + \
                self.processName + "' WHERE name = '" + resource + "'"

            self.cursor.execute(update_isSeized_usedBy_resource_query)
            self.connection.commit()
            if result[0][0] == 'Conveyor Station':
                if self.runType == 'RealRun':
                    messageTopic = 'plcHandler/request/'+resource+'/'+conveyorArg+'/'+taskID
                    self.mqttClient.publish(messageTopic, outcomeTopic)
                    return

                else:
                    self.mqttClient.publish(outcomeTopic)


            update_task_complete_process_query = "UPDATE process_handler SET task_complete = True, end_time = " + \
                str(time.time()) + " WHERE task_name = '" + task + "' AND process_name = '" + self.processName + "' AND operation_name = '" + self.operationName + "'"

            self.cursor.execute(update_task_complete_process_query)
            self.connection.commit()
            
            print(datetime.datetime.now(),self.processName,task,resource,conveyorArg,'\t\tSeize Request GRANTED.')

        elif self.isSeized(resource) == 1:
            print(datetime.datetime.now(),self.processName,task,resource,conveyorArg,'\t\t\tSeize Request DENIED.')

            outcomeTopic = \
                'resourceHandler/response/resourceSeize/' + \
                self.processName + '/' + \
                task + '/' + \
                resource + '/DENIED'

            self.mqttClient.publish(outcomeTopic)
            self.connection.commit()

            self.connection.commit()

    def outcomeSeize(self, client, userdata, msg):
        print('Running outcome seized callback!')
        msg = msg.topic.split('/')
        
        task = msg[-3:][0]
        resource = msg[-2:][0]
        outcome = msg[-1:][0]
        outcome = True if outcome == 'GRANTED' else False

        
        
        if outcome == True:
            print(datetime.datetime.now(),self.processName,task,resource,'\t\tSeize Request GRANTED.')
            
            update_task_complete_process_query = "UPDATE process_handler SET task_complete = True, end_time = " + \
                str(time.time()) + " WHERE task_name = '" + task + "' AND process_name = '" + self.processName + "' AND operation_name = '" + self.operationName + "'"
            self.cursor.execute(update_task_complete_process_query)
            self.connection.commit()

    def functionalPrinting(self, mqttTopic):
        processInfo = mqttTopic.split('/')
        task = processInfo[1]
        taskID = processInfo[0]

        print('Starting functional printing')

        exec(open('_mesFunctionalPrintingInit.py').read())

        update_task_complete_process_query = "UPDATE process_handler SET task_complete = True, end_time = " + \
            str(time.time()) + " WHERE task_name = '" + task + "' AND process_name = '" + self.processName + "' AND operation_name = '" + self.operationName + "'"
        self.cursor.execute(update_task_complete_process_query)
        self.connection.commit()

        '''update_task_complete_process_query = "UPDATE process_handler SET task_complete = True, end_time = " + \
            str(time.time()) + " WHERE id = " + str(taskID)
        self.cursor.execute(update_task_complete_process_query)
        self.connection.commit()'''

        print('Functional printing completed')

    def circuitVision_complete(self, mqttTopic):
        processInfo = mqttTopic.split('/')
        task = processInfo[1]
        taskID = processInfo[0]

        print('Starting test')

        exec(open('_mesCircuitVision_complete.py').read())

        update_task_complete_process_query = "UPDATE process_handler SET task_complete = True, end_time = " + \
            str(time.time()) + " WHERE task_name = '" + task + "' AND process_name = '" + self.processName + "' AND operation_name = '" + self.operationName + "'"
        self.cursor.execute(update_task_complete_process_query)
        self.connection.commit()

    def runCalibration(self, mqttTopic):
        processInfo = mqttTopic.split('/')
        task = processInfo[1]
        taskID = processInfo[0]

        print('run calibration')

        exec(open('_mesrunCalibration.py').read())

        update_task_complete_process_query = "UPDATE process_handler SET task_complete = True, end_time = " + \
            str(time.time()) + " WHERE task_name = '" + task + "' AND process_name = '" + self.processName + "' AND operation_name = '" + self.operationName + "'"
        self.cursor.execute(update_task_complete_process_query)
        self.connection.commit()

        '''update_task_complete_process_query = "UPDATE process_handler SET task_complete = True, end_time = " + \
            str(time.time()) + " WHERE id = " + str(taskID)
        self.cursor.execute(update_task_complete_process_query)
        self.connection.commit()'''

        print('Calibration completed')


    # this command is generated within self.checkCurrentTask
    def resourceRelease(self, mqttTopic, resource, conveyorArg=None):
        processInfo = mqttTopic.split('/')
        task = processInfo[1]
        taskID = processInfo[0]

        # Update resource table seized and usedBy field for currently selected resource
        update_isSeized_usedBy_resource_query = "UPDATE resource_handler SET isSeized = False, usedBy = '' WHERE name = '" + \
            resource + "'"

        self.cursor.execute(update_isSeized_usedBy_resource_query)
        self.connection.commit()

        update_task_complete_process_query = "UPDATE process_handler SET task_complete = True, end_time = " + \
            str(time.time()) + " WHERE id = " + str(taskID)
        self.cursor.execute(update_task_complete_process_query)
        self.connection.commit()

        print(datetime.datetime.now(),self.processName,task,resource,'\t\t\tRelease Request GRANTED.')

        outcomeTopic = \
            'resourceHandler/response/resourceRelease/' + \
            self.processName + '/' + \
            task + '/' + \
            resource + '/GRANTED'

        # Check resource table to see if the selected resource is a Conveyor Station
        select_type_resource_query = "SELECT type FROM resource_handler WHERE name = '" + \
                resource + "' LIMIT 1"

        self.cursor.execute(select_type_resource_query)
        result = self.cursor.fetchall()

        if result[0][0] == 'Conveyor Station':
            if self.runType == 'RealRun':
                messageTopic = 'plcHandler/release/'+resource
                self.mqttClient.publish(messageTopic, outcomeTopic)
            else:
                self.mqttClient.publish(outcomeTopic)
        else:
            self.mqttClient.publish(outcomeTopic)
        
    def startupTasksComplete(self, mqttTopic):
        messageTopic = 'mesBackend/startup/' + mqttTopic
        task = mqttTopic.split('/')[1]
        print('Sending message to startup ' + messageTopic)
        self.mqttClient.publish(messageTopic, self.processName)

        update_task_complete_process_query = "UPDATE process_handler SET task_complete = True, end_time = " + \
            str(time.time()) + " WHERE task_name = '" + task + "' AND process_name = '" + self.processName + "' AND operation_name = '" + self.operationName + "'"
        self.cursor.execute(update_task_complete_process_query)
        self.connection.commit()

    def scheduleFullSimTask(self,task,simTime=0.5):
        self.currentTaskFullSim = task
        schedule.every(simTime).seconds.do(self.executeFullSimTask)
    
    def executeFullSimTask(self):
        update_task_complete_process_query = "UPDATE process_handler SET task_complete = True, end_time = " + \
            str(time.time()) + " WHERE task_name = '" + self.currentTaskFullSim + "' AND process_name = '" + self.processName + "' AND operation_name = '" + self.operationName + "'"
        self.cursor.execute(update_task_complete_process_query)
        self.connection.commit()

        return schedule.CancelJob

    def urDashboard(self, mqttTopic, robot, urpFile, fullSimTime=0.5):
        # mqttTopic is example: 1of3/task_3
        # It used to contain the process name in the first index, since operation was previously joined to this
        # This was changed when DB was implemented and now only has the operation number, 
        # which conflicts with other processes running

        topic = mqttTopic.split('/')
        task = topic[1]
        taskID = topic[0]

        # mqttTopic is now: BCordganizerLid/1of3/task_3
        mqttTopic = self.processName + '/' + mqttTopic

        if self.runType == 'FullSim':

            insert_task_data_handler_query = "INSERT INTO handler_requests (handler, process_name, operation_name, task_name, machine, command, taskID, received, task_executing) VALUES ('urHandler', '" + \
                self.processName + "', '" + self.operationName + "', '" + task + "', '" + robot + "', '" + urpFile + "', " + taskID + ", False, False)"

            self.cursor.execute(insert_task_data_handler_query)
            self.connection.commit()     
               
            self.scheduleFullSimTask(task,fullSimTime)
        elif self.runType == 'QuickSim':
            
            update_task_complete_process_query = "UPDATE process_handler SET task_complete = True, end_time = " + \
                str(time.time()) + " WHERE task_name = '" + task + "' AND process_name = '" + self.processName + "' AND operation_name = '" + self.operationName + "'"
            self.cursor.execute(update_task_complete_process_query)
            self.connection.commit()
        
        elif self.runType == 'RealRun':
            # mqttTopic is example: BCordganizerLid/1of3/task_3
            # the full message topic is therefore urHandler/request/BCordganizerLid/1of3/task_3
            mqttTopic = 'urHandler/request/'+ mqttTopic


            insert_task_data_handler_query = "INSERT INTO handler_requests (handler, process_name, operation_name, task_name, machine, command, taskID, received, task_executing) VALUES ('urHandler', '" + \
                self.processName + "', '" + self.operationName + "', '" + task + "', '" + robot + "', '" + urpFile + "', " + taskID + ", False, False)"

            self.cursor.execute(insert_task_data_handler_query)
            self.connection.commit()

            self.mqttClient.publish(mqttTopic, robot+'~'+urpFile)

    def outcomeUrDashboard(self, client, userdata, msg):
        # when a message comes back with topic urHandler/outcome/#
        # it will have the full topic name of urHandler/request/BCordganizerLid/1of3/task_3, for example
        taskID = msg.topic.split('/')[0]
        task = (msg.topic.split('/'))[-1]  # returns 'task_3'
        if msg.payload.decode() == 'SUCCESS':          
            update_task_complete_process_query = "UPDATE process_handler SET task_complete = True, end_time = " + \
                str(time.time()) + " WHERE task_name = '" + task + "' AND process_name = '" + self.processName + "' AND operation_name = '" + self.operationName + "'"
            self.cursor.execute(update_task_complete_process_query)
            self.connection.commit()

    def cncRun(self, mqttTopic, machine, gcode, fullSimTime=0.5):
        if self.runType == 'FullSim':

            # self.scheduleFullSimTask(task,fullSimTime)
            taskID = mqttTopic.split('/')[0]
            task = mqttTopic.split('/')[1]
            mqttTopic = 'cncHandler/request/' + mqttTopic
            # self.mqttClient.publish(mqttTopic, machine+'~'+gcode)
            # self.mqttClient.publish('debug',gcode)
            update_task_complete_process_query = "UPDATE process_handler SET task_complete = True, end_time = " + \
                str(time.time()) + " WHERE task_name = '" + task + "' AND process_name = '" + self.processName + \
                    "' AND operation_name = '" + self.operationName + "'"
            self.cursor.execute(update_task_complete_process_query)
            self.connection.commit()

            self.mqttClient.publish(mqttTopic)

        elif self.runType == 'QuickSim':
            task = mqttTopic.split('/')[1]

            update_task_complete_process_query = "UPDATE process_handler SET task_complete = True, end_time = " + \
                str(time.time()) + " WHERE task_name = '" + task + "' AND process_name = '" + self.processName + \
                    "' AND operation_name = '" + self.operationName + "'"
            self.cursor.execute(update_task_complete_process_query)
            self.connection.commit()
        
        elif self.runType == 'RealRun':
            taskID = mqttTopic.split('/')[0]
            task = mqttTopic.split('/')[1]
            mqttTopic = 'cncHandler/request/' + mqttTopic
            # self.mqttClient.publish(mqttTopic, machine+'~'+gcode)
            # self.mqttClient.publish('debug',gcode)

            print('GOT TO ADDING HANDLER REQUEST')
            insert_task_data_handler_query = "INSERT INTO handler_requests (handler, process_name, operation_name, task_name, machine, command, taskID, received, task_executing) VALUES ('cncHandler', '" + \
                self.processName + "', '" + self.operationName + "', '" + task + "', '" + machine + "', '" + gcode + "'," + taskID + ", False, False)"
            print(insert_task_data_handler_query)
            self.cursor.execute(insert_task_data_handler_query)
            self.connection.commit()
            print('PASSED ADDING HANDLER REQUEST')

            self.mqttClient.publish(mqttTopic)
    
    def outcomeCncRun(self, client, userdata, msg):
        print('CNC OUTCOME MESSAGE RECEIVED')
        #when a message comes back with topic urHandler/outcome/#
        # it will have the full topic name of urHandler/request/testURP_1of3/task_3, for example
        task = (msg.topic.split('/'))[-1]  # returns 'task_3'
        # self.mqttClient.publish('debug', str(task))
        if msg.payload.decode() == 'SUCCESS':
            update_task_complete_process_query = "UPDATE process_handler SET task_complete = True, end_time = " + \
                str(time.time()) + " WHERE task_name = '" + task + "' AND process_name = '" + self.processName + "' AND operation_name = '" + self.operationName + "'"
            self.cursor.execute(update_task_complete_process_query)
            self.connection.commit()

    def visionInspection(self, mqttTopic, cameraID, solutionID, variable, fullSimTime=0.5):
        if self.runType == 'FullSim':
            task = mqttTopic.split('/')[1]
            self.scheduleFullSimTask(task,fullSimTime)
        
        elif self.runType == 'QuickSim':
            task = mqttTopic.split('/')[1]

            update_task_complete_process_query = "UPDATE process_handler SET task_complete = True, end_time = " + \
                str(time.time()) + " WHERE task_name = '" + task + "' AND process_name = '" + self.processName + "' AND operation_name = '" + self.operationName + "'"
            self.cursor.execute(update_task_complete_process_query)
            self.connection.commit()
        
        elif self.runType == 'RealRun':
            # mqttTopic is example: testURP_1of3/task_3
            # the full message topic is therefore urHandler/request/testURP_1of3/task_3
            task = mqttTopic.split('/')[1]
            mqttTopic = 'visionHandler/request/'+mqttTopic
            self.mqttClient.publish(mqttTopic, cameraID+'~'+solutionID+'~'+variable)

    def outcomeVisionInspection(self, client, userdata, msg):
        # when a message comes back with topic urHandler/outcome/#
        # it will have the full topic name of urHandler/request/testURP_1of3/task_3, for example
        task = (msg.topic.split('/'))[-1]  # returns 'task_3'
        
        update_task_complete_process_query = "UPDATE process_handler SET task_complete = True, end_time = " + \
            str(time.time()) + " WHERE task_name = '" + task + "' AND process_name = '" + self.processName + "' AND operation_name = '" + self.operationName + "'"
        self.cursor.execute(update_task_complete_process_query)
        self.connection.commit()

    def endProcess(self, mqttTopic):
        print('It made it this far')
        task = mqttTopic.split('/')[1]

        update_task_complete_process_query = "UPDATE process_handler SET task_complete = True, end_time = " + \
            str(time.time()) + " WHERE task_name = '" + task + "' AND process_name = '" + self.processName + "' AND operation_name = '" + self.operationName + "'"
        self.cursor.execute(update_task_complete_process_query)
        self.connection.commit()

        # self.writeProcessReport()
        self.isThisProcessComplete = True
        messageTopic = \
            'backend/endProcess/' + \
            self.processName + '/' + \
            self.operationName
        self.mqttClient.publish(messageTopic)

    def systemStatusCallback(self, client, userdata, msg):
        msg.payload = msg.payload.decode()
        if msg.payload.split('/')[0] == 'Stopped':
            self.mqttClient.publish('debug', 'Stopping _mesProcess')
            self.connection.disconnect()
            self.quit = True

    def loopProcess(self):
        try:
            while not self.isThisProcessComplete and not self.quit:
                schedule.run_pending()
                self.mqttClient.loop(0.1)
            sys.exit(0)
        except Exception as e:
            self.mqttClient.publish('debug', str(e))
            sys.exit(0)

        # try:
        #     while not self.isThisProcessComplete: # and not self.quit:
        #         schedule.run_pending()
        #         self.mqttClient.loop(0.1)
        # except Exception as e:
        #     self.mqttClient.publish('debug', str(e))
        #     print(e)

process = mesProcess()

# if __name__ == "__main__":
#     mesProcess.circuitVision_test1()