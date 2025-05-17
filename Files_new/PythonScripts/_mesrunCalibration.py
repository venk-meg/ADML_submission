"""
Script executed with BUMES command: --- "functionalPrinting()" ---
"""

import os

def runPythonScript(filename):
    """
    Finds and executes the python script with given filename
    """

    command = 'python.exe "' + str(filename) + '"'
    print(command)
    os.system(command)


runPythonScript('C:\git\ADML\Functional Printing Calibration\calibration.py')
