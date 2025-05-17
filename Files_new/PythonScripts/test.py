#run meander print
#vice to camera
#camera_test_ meander
#if pass, meadner test to side and continue
        #if fail, meadner test discard and and stop (home robot)
#conveyor to camera
#cnc_test_camera
#if pass, camera to vice and continue
        #if fail, cnc test discard and and stop (home robot)
#call funcitonal printing
#circuit: vice to camera
#test for placements
#if pass, circuit from camera to side (finish)
    #if fail, circuit discard (fail)

#list of progs:

# "TUES_530PM/Project1pick.urp" conveyor to camera
# "TUES_530PM/Project1pick2.urp" camera to vice
# "TUES_530PM/Project1pick3.urp" vice to camera
# "TUES_530PM/Project1pick4.urp" camera to good circuit output
# "TUES_530PM/Project1pick5.urp" camera to meander output
# "TUES_530PM/Project1pick6.urp" camera to bad circuit output

import rtde_control
import rtde_receive
import rtde_io
# from rtde import rtde
import socket
from coreModule import *
# rtde_c = rtde_control.RTDEControlInterface("10.241.34.45")
# rtde_r = rtde_receive.RTDEReceiveInterface("10.241.34.45")
# rtde_io_ = rtde_io.RTDEIOInterface("10.241.34.45")
import time
import circuitvision_test_main
import sys
import os
import datetime
import meander_print
import demoCircuit


ROBOT_IP = "10.241.34.45"  # Rosie's IP

def runPythonScript(filename):
    """
    Finds and executes the python script with given filename
    """

    command = 'python.exe "' + str(filename) + '"'
    print(command)
    os.system(command)

def robot_command(program_name):

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((ROBOT_IP, 29999))

    # Stop any running program
    s.send(b"stop\n")
    time.sleep(0.5)

    # Load the program
    s.send(f"load {program_name}\n".encode())
    time.sleep(0.5)

    # Play the program
    s.send(b"play\n")
    time.sleep(0.5)

    while rtde_control.isProgramRunning():
        # print('running')
        time.sleep(0.5)
        
    rtde_control.disconnect()
    # Close the connection
    s.close()
    rtde_control.reconnect()
    # rtde_control.stopScript()

    ####

def logging(input):
    now = datetime.datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    with open("Vision_test_log", "a") as f:
        f.write(str((timestamp, input)))
    f.close()
    
def test_and_move(test_name):
    try:
        ok = circuitvision_test_main.run_image_test(test_name)
        logging((test_name, ok))

        if not ok:
            #if fail, cnc test discard 
            robot_command("TUES_530PM/Project1pick6.urp")
            #and stop 
            sys.exit()
    except: 
            robot_command("TUES_530PM/Project1pick6.urp")
            #and stop 
            sys.exit()
  

def main():
    robot_command("TUES_530PM/Project1pick.urp")
    #cnc_test_camera


if __name__ == "__main__":
    main()
    rtde_control.stopScript()