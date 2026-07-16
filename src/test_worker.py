"""Background worker for production DUT test execution."""

import os
import threading
import traceback
from enum import Enum
from time import monotonic as monotonic_time

import pandas as pd
from PyQt5.QtCore import QThread, pyqtSignal

from path import csv_folder
from data import (
    datatoCSV_Accuracy,
    datatoCSV_Accuracy2,
    datatoCSV_Line_Regulation,
    datatoCSV_LoadRegulation,
    datatoCSV_OCP_Test,
    datatoCSV_OVP_Accuracy,
    datatoCSV_PowerAccuracy,
    datatoCSV_Programming_Response,
    datatoGraph,
    datatoGraph2,
    datatoGraph3,
    instrumentData,
    powerinstrumentData,
)
from xlreport import xlreport
from xlreportpower import xlreportpower
from DUT_Test_Scripts.DUT_Test import NewCurrentMeasurement, NewVoltageMeasurement
from DUT_Test_Scripts.Dolphin_DUT_Test_No_ELoad_No_DMM import (
    LineRegulation,
    NewLoadRegulation,
    OCP_Activation_Time,
    OVP_Test,
    PowerMeasurement,
    ProgrammingResponse,
    RiseFallTime,
)
from DUT_Test_Scripts.Hornbill_DUT_Test_With_ELoad import (
    HornbillCurrentMeasurementwithELoad_IMON_200uA,
    HornbillCurrentMeasurementwithELoad_IMON_2mA,
    HornbillVoltageMeasurementwithELoad,
)
from DUT_Test_Scripts.execution_control import clear_execution_worker, set_execution_worker
from DUT_Test_Scripts.instrument_shutdown import shutdown_instruments
from SCPI_Library.instrument_errors import (
    CleanupError,
    clear_diagnostic_context,
    normalize_execution_error,
    set_diagnostic_context,
)
from SCPI_Library.session_manager import begin_visa_session_scope, close_visa_session_scope
from SCPI_Library.simulation import is_simulation_mode

class TestState(Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"


class TestCancelled(Exception):
    pass


class TestWorker(QThread):
    progress = pyqtSignal(str)
    progress_value = pyqtSignal(int) 
    finished = pyqtSignal()
    error = pyqtSignal(Exception, str)
    warning = pyqtSignal(Exception, str)
    aborted = pyqtSignal() 
    new_data = pyqtSignal(float, float, float, float, float, float, float, float, float, float, float, float, float, float, float)  #Shamman changes for Vset, Iset, PSU readback voltage, and PSU readback current 
    popup_data = pyqtSignal(float, float, float, float, float, float, float, float, float, float) #Shamman changes
    test_failed = pyqtSignal(dict)   # send context
    resume_test = pyqtSignal()
    stop_test = pyqtSignal()
    state_changed = pyqtSignal(str)
    #fail_signal = pyqtSignal(float)     # send error value
    #decision_signal = pyqtSignal(bool)  # receive Continue / Abort

    def __init__(self, checkbox_state, dict, params):
        super().__init__()
        self.params = params  # shared Parameters object
        self.run_context = params.get("run_context")
        self.checkbox_states = checkbox_state
        self.dict = dict

        self.infoList = []
        self.dataList = []
        self.dataList2 = []
        self.ProgrammingV_percent_error_list = []
        self.ReadbackV_percent_error_list = []
        self.results = []
        self.results2 = []
        self.currenttime = None

        self.was_aborted = False
        self._control = threading.Condition()
        self._paused = False
        self._stop_requested = False
        self.state = TestState.IDLE
        self.force_exit = False   # ✅ Add this line

    def _set_state(self, state):
        if state == self.state:
            return
        self.state = state
        self.state_changed.emit(state.value)

    @property
    def is_paused(self):
        with self._control:
            return self._paused

    def pause(self):
        with self._control:
            if not self._stop_requested and self.state == TestState.RUNNING:
                self._paused = True
                self._set_state(TestState.PAUSED)

    def resume(self):
        with self._control:
            if self.state != TestState.PAUSED:
                return
            self._paused = False
            self._set_state(TestState.RUNNING)
            self._control.notify_all()

    def stop(self):
        self.request_stop()

    def request_stop(self):
        with self._control:
            if self._stop_requested:
                return
            self._stop_requested = True
            self._paused = False
            self.was_aborted = True
            self._set_state(TestState.STOPPING)
            self._control.notify_all()

    def checkpoint(self):
        with self._control:
            while self._paused and not self._stop_requested:
                self._control.wait(timeout=0.25)
            if self._stop_requested:
                raise TestCancelled("Test stopped by operator")

    def interruptible_sleep(self, seconds):
        deadline = monotonic_time() + max(0.0, float(seconds))
        while True:
            self.checkpoint()
            remaining = deadline - monotonic_time()
            if remaining <= 0:
                return
            with self._control:
                self._control.wait(timeout=min(0.1, remaining))

    def safe_shutdown(self):
        result = shutdown_instruments(self.dict)
        if result.succeeded:
            return

        failure_details = [failure.to_dict() for failure in result.failures]
        traceback_text = "\n\n".join(
            failure.traceback_text for failure in result.failures
        )
        cleanup_error = CleanupError(
            f"Instrument shutdown completed with {len(result.failures)} warning(s)",
            operation="shutdown_instruments",
            dut=self.params.get("DUT"),
            attempted_roles=list(result.attempted_roles),
            failures=failure_details,
        )
        self.warning.emit(cleanup_error, traceback_text)

    def close_visa_sessions(self):
        failures = close_visa_session_scope()
        if not failures:
            return

        cleanup_error = CleanupError(
            f"VISA session cleanup completed with {len(failures)} warning(s)",
            operation="close_visa_sessions",
            dut=self.params.get("DUT"),
            failures=[failure.to_dict() for failure in failures],
        )
        traceback_text = "\n\n".join(
            failure.traceback_text for failure in failures
        )
        self.warning.emit(cleanup_error, traceback_text)

    '''@pyqtSlot(bool)         #Shamman changes
    def receive_decision(self, decision):
        self.decision = decision'''

    def _write_config_csv(self, file_name):
        config_frame = pd.DataFrame.from_dict(self.dict, orient="index")
        config_frame.index.name = "Parameter"
        config_frame.columns = ["Value"]
        output_directory = (
            self.run_context.storage.raw if self.run_context else csv_folder
        )
        config_frame.to_csv(os.path.join(output_directory, file_name))

    def _save_voltage_report(self):
        file_name = str(self.params["unit"])
        if is_simulation_mode():
            file_name = f"SIMULATED_{file_name}"
        report = xlreport(
            save_directory=self.params["savelocation"],
            file_name=file_name,
        )
        report.run()
        self.progress.emit(
            "Excel Report Saved: " + str(self.params["savelocation"])
        )
        self.progress.emit("")

    def _save_power_report(self):
        file_name = (
            "Power_CV" if self.params["setFunction"] == "Current" else "Power_CC"
        )
        if is_simulation_mode():
            file_name = f"SIMULATED_{file_name}"
        report = xlreportpower(
            save_directory=self.params["savedir"], file_name=file_name
        )
        report.run()
        self.progress.emit("Excel Report Saved: " + str(self.params["savedir"]))
        self.progress.emit("")

    def _dispatch_dut_tests(self, loop_index):
        if self.params["DUT"] == "Dolphin":
            self._run_dolphin_tests(loop_index)
        elif self.params["DUT"] == "Hornbill":
            self._run_hornbill_tests(loop_index)

    def _run_dolphin_tests(self, loop_index):
        if self.checkbox_states["Voltage_Test"]:
            self._run_dolphin_voltage_tests(loop_index)
        elif self.checkbox_states["Current_Test"]:
            self._run_dolphin_current_tests(loop_index)

        if self.force_exit:
            return

        if not self.force_exit:
            self.progress_value.emit(100)
            self.progress.emit("All measurements completed!")

    def _run_dolphin_voltage_tests(self, loop_index):
        x = loop_index
        #Voltage Accuracy
        if self.checkbox_states.get("VoltageAccuracy"):
            if self.dict["Instrument"] == "Keysight":
                if self.checkbox_states.get("CurrentStatic(VoltageChange)"):
                    for ch in self.dict["PSU_Channel"]:
                        (infoList,
                        dataList,
                        dataList2)= NewVoltageMeasurement.Execute_Voltage_Accuracy_Current_Static(self, self.dict, ch, worker=self)

                        #Measurement Completion
                        if (int(self.params["noofloop"]) - 1) <= 0:
                            self.progress.emit("✅Measurement is complete !")

                            #Export Data to CSV
                            if self.checkbox_states["DataReport"]:

                                #Export data to CSV and Graph (Refer data.py for details)
                                instrumentData(self.params["PSU"], self.params["DMM"], self.params["ELoad"])
                                datatoCSV_Accuracy(infoList, dataList, dataList2)
                                datatoGraph(infoList, dataList,dataList2)
                                datatoGraph.scatterCompareVoltage(self, float(self.params["Programming_Error_Gain"]), float(self.params["Programming_Error_Offset"]), float(self.params["Readback_Error_Gain"]), float(self.params["Readback_Error_Offset"]), str(self.params["unit"]), float(self.params["Voltage_Rating"]))

                                self._write_config_csv("config.csv")

                                self._save_voltage_report()

                elif self.checkbox_states.get("CurrentChange(LoadChange)"):
                    for ch in self.dict["PSU_Channel"]:
                        (infoList,
                        dataList,
                        dataList2)= NewVoltageMeasurement.Execute_Voltage_Accuracy_Current_Change(self, self.dict, ch, worker=self)

                        #Measurement Completion
                        if (int(self.params["noofloop"]) - 1) <= 0:
                            self.progress.emit("✅Measurement is complete !")

                            #Export Data to CSV
                            if self.checkbox_states["DataReport"]:

                                #Export data to CSV and Graph (Refer data.py for details)
                                instrumentData(self.params["PSU"], self.params["DMM"], self.params["ELoad"])
                                datatoCSV_Accuracy(infoList, dataList, dataList2)
                                datatoGraph(infoList, dataList,dataList2)
                                datatoGraph.scatterCompareVoltage(self, float(self.params["Programming_Error_Gain"]), float(self.params["Programming_Error_Offset"]), float(self.params["Readback_Error_Gain"]), float(self.params["Readback_Error_Offset"]), str(self.params["unit"]), float(self.params["Voltage_Rating"]))

                                self._write_config_csv("config.csv")

                                self._save_voltage_report()

        #Voltage Load Regulation
        if self.checkbox_states.get("VoltageLoadRegulation"):
            if self.params["Instrument"] == "Keysight":
                for ch in self.params["PSU_Channel"]:
                    self.results = NewLoadRegulation.executeCV_LoadRegulation(self, self.dict)
                    os.system('cls')
                    datatoCSV_LoadRegulation(self.results, self.params)

        #Transient Recovery
        if self.checkbox_states.get("TransientRecovery"):
            if self.checkbox_states["SpecialCase"]:
                RiseFallTime.executeC(self, self.dict)

            if self.checkbox_states["NormalCase"]:
                RiseFallTime.executeC(self, self.dict)

        #OVP Accuracy Test
        if self.checkbox_states.get("OVP_Test"):
            self.results = OVP_Test.Execute_OVP(self,self.dict)
            os.system('cls')
            datatoCSV_OVP_Accuracy(self.results, self.params)

        #Voltage Line RegulationW
        if self.checkbox_states.get("VoltageLineRegulation"):
            self.results = LineRegulation.executeCV_LoadRegulation(self, self.dict)
            #os.system('cls')
            datatoCSV_Line_Regulation(self.results, self.params)

        #Programming Responses
        if self.checkbox_states.get("ProgrammingSpeed"):
            test = ProgrammingResponse()
            self.results, self.currenttime = test.execute(self.dict)
            os.system('cls')
            datatoCSV_Programming_Response(self.results,self.currenttime,self.params)

    def _run_dolphin_current_tests(self, loop_index):
        x = loop_index
        #Current Accuracy Test
        if self.checkbox_states.get("CurrentAccuracy"):
            if self.dict["Instrument"] == "Keysight":
                for ch in self.params["PSU_Channel"]:
                    (infoList,
                    dataList,
                    dataList2) = NewCurrentMeasurement.executeCurrentMeasurementA(self, self.dict, ch)

                    #Measurement Completion
                    if x == (int(self.params["noofloop"]) - 1):
                        self.progress.emit("✅Measurement is complete !")

                        #Export Data to CSV
                        if self.checkbox_states["DataReport"]:

                            #Export data to CSV and Graph (Refer data.py for details)
                            instrumentData(self.params["PSU"], self.params["DMM"], self.params["ELoad"])
                            datatoCSV_Accuracy2(infoList, dataList, dataList2)
                            datatoGraph2(infoList, dataList,dataList2)
                            datatoGraph2.scatterCompareCurrent2(self, float(self.params["Programming_Error_Gain"]), float(self.params["Programming_Error_Offset"]), float(self.params["Readback_Error_Gain"]), float(self.params["Readback_Error_Offset"]), str(self.params["unit"]), float(self.params["I_Rating"]))

                            self._write_config_csv("config.csv")

                            #Read error,config and instrumentData files, then combine to (self.params.unit) file (Refer xlreport for details)
                            A = xlreport(save_directory=self.params["savelocation"], file_name=str(self.params["unit"]))
                            A.run()
                            self.progress.emit("Excel Report Saved: " + str(self.params["savedir"]))
                            self.progress.emit("")

                    if self.force_exit:
                        self.progress.emit("Operation aborted")
                        return  # Exit immediately

        #Current Load Regulation Test
        if self.checkbox_states.get("CurrentLoadRegulation"):
            if self.params["Instrument"] == "Keysight":
                for ch in self.params["PSU_Channel"]:
                    self.results = NewLoadRegulation.executeCC_LoadRegulation(self, self.dict)
                    os.system('cls')
                    datatoCSV_LoadRegulation(self.results, self.params)

        #Power Accuracy Test
        if self.checkbox_states.get("PowerAccuracy"):
            if self.checkbox_states["Voltage_Test"]:
                infoList, dataList, dataList2 = PowerMeasurement.executePowerMeasurementB(self, self.dict)  # Power CC

            elif self.checkbox_states["Current_Test"]:
                infoList, dataList, dataList2 = PowerMeasurement.executePowerMeasurementA(self, self.dict)  # Power CV

            #Measurement Completion
            if x == (int(self.params["noofloop"]) - 1):
                self.progress.emit("✅Measurement is complete !")

                #Export Data to CSV
                if self.checkbox_states["DataReport"]:

                    #Export data to CSV and Graph (Refer data.py for details)
                    powerinstrumentData(self.params["PSU"], self.params["DMM"], self.params["DMM2"], self.params["ELoad"])
                    datatoCSV_PowerAccuracy(infoList, dataList, dataList2)
                    datatoGraph3(infoList, dataList,dataList2)
                    datatoGraph3.scatterComparePower(self, float(self.params["Power_Programming_Error_Gain"]), float(self.params["Power_Programming_Error_Offset"]), float(self.params["Power_Readback_Error_Gain"]), float(self.params["Power_Readback_Error_Offset"]), str(self.params["setFunction"]), float(self.params["P_Rating"]))

                    self._write_config_csv("powerconfig.csv")

                    self._save_power_report()

        #Current Line Regulation
        if self.checkbox_states.get("CurrentLineRegulation"):
            self.results = LineRegulation.executeCC_LoadRegulation(self, self.dict)
            datatoCSV_Line_Regulation(self.results, self.params)

        #OCP Accuracy Test
        if self.checkbox_states.get("OCP_Test"):

            #Accuracy Test 1st
            #OCP_test = OCP_Accuracy()
            #self.results = OCP_test.Execute_OCP(dict)
            #os.system('cls')
            # OCP_data_export = datatoCSV_OCP_Test(params)
            #OCP_data_export.AccuracyTest(self.results)

            self.results =[]

            #Activation Time Test
            OCP_test2 = OCP_Activation_Time()
            self.results = OCP_test2.Execute_OCP(self.dict)
            OCP_data_export2 = datatoCSV_OCP_Test(self.params)
            OCP_data_export2.ActivationTime(self.results)

    def _run_hornbill_tests(self, loop_index):
        if self.checkbox_states["Voltage_Test"]:
            self._run_hornbill_voltage_tests(loop_index)
        elif self.checkbox_states["Current_Test"]:
            self._run_hornbill_current_tests(loop_index)

        if self.force_exit:
            return

        if not self.force_exit:
            self.progress_value.emit(100)
            self.progress.emit("All measurements completed!")
        else:
            self.progress.emit("No DUT selected. Please select a DUT to perform the test.")

    def _run_hornbill_voltage_tests(self, loop_index):
        x = loop_index
        #Voltage Accuracy
        if self.checkbox_states.get("VoltageAccuracy"):
            if self.checkbox_states.get("CurrentStatic(VoltageChange)"):
                if self.dict["Instrument"] == "Keysight":
                    for ch in self.dict["PSU_Channel"]:
                        (infoList,
                        dataList,
                        dataList2)= HornbillVoltageMeasurementwithELoad.Execute_Voltage_Accuracy_Current_Static(self, self.dict, ch, worker=self)

                        #Measurement Completion
                        self.progress.emit(f"✅ {int(self.params['noofloop'])} Measurement is complete !")


                        #Export Data to CSV
                        #if self.checkbox_states["DataReport"]:

                        #Export data to CSV and Graph (Refer data.py for details)
                        instrumentData(self.params["PSU"], self.params["DMM"], self.params["ELoad"])
                        datatoCSV_Accuracy(infoList, dataList, dataList2)
                        datatoGraph(infoList, dataList,dataList2)
                        datatoGraph.scatterCompareVoltage(self, float(self.params["Programming_Error_Gain"]), float(self.params["Programming_Error_Offset"]), float(self.params["Readback_Error_Gain"]), float(self.params["Readback_Error_Offset"]), str(self.params["unit"]), float(self.params["Voltage_Rating"]))

                        self._write_config_csv("config.csv")

                        self._save_voltage_report()

            elif self.checkbox_states.get("CurrentChange(LoadChange)"):
                if self.dict["Instrument"] == "Keysight":
                    for ch in self.dict["PSU_Channel"]:
                        (infoList,
                        dataList,
                        dataList2)= HornbillVoltageMeasurementwithELoad.Execute_Voltage_Accuracy_Current_Change(self, self.dict, ch, worker=self)

                        #Measurement Completion
                        if (int(self.params["noofloop"]) - 1) <= 0:
                            self.progress.emit("✅Measurement is complete !")

                            #Export Data to CSV
                            if self.checkbox_states["DataReport"]:

                                #Export data to CSV and Graph (Refer data.py for details)
                                instrumentData(self.params["PSU"], self.params["DMM"], self.params["ELoad"])
                                datatoCSV_Accuracy(infoList, dataList, dataList2)
                                datatoGraph(infoList, dataList,dataList2)
                                datatoGraph.scatterCompareVoltage(self, float(self.params["Programming_Error_Gain"]), float(self.params["Programming_Error_Offset"]), float(self.params["Readback_Error_Gain"]), float(self.params["Readback_Error_Offset"]), str(self.params["unit"]), float(self.params["Voltage_Rating"]))

                                self._write_config_csv("config.csv")

                                self._save_voltage_report()

            elif self.checkbox_states.get("CurrentStatic(VoltageChange) with Oscilloscope"):
                if self.dict["Instrument"] == "Keysight":
                    for ch in self.dict["PSU_Channel"]:
                        (infoList,
                        dataList,
                        dataList2)= HornbillVoltageMeasurementwithELoad.Execute_Voltage_Accuracy_Current_Change(self, self.dict, ch, worker=self)

                        #Measurement Completion
                        if (int(self.params["noofloop"]) - 1) <= 0:
                            self.progress.emit("✅Measurement is complete !")

                            #Export Data to CSV
                            if self.checkbox_states["DataReport"]:

                                #Export data to CSV and Graph (Refer data.py for details)
                                instrumentData(self.params["PSU"], self.params["DMM"], self.params["ELoad"])
                                datatoCSV_Accuracy(infoList, dataList, dataList2)
                                datatoGraph(infoList, dataList,dataList2)
                                datatoGraph.scatterCompareVoltage(self, float(self.params["Programming_Error_Gain"]), float(self.params["Programming_Error_Offset"]), float(self.params["Readback_Error_Gain"]), float(self.params["Readback_Error_Offset"]), str(self.params["unit"]), float(self.params["Voltage_Rating"]))

                                self._write_config_csv("config.csv")

                                self._save_voltage_report()

        #Voltage Load Regulation
        if self.checkbox_states.get("VoltageLoadRegulation"):
            if self.params["Instrument"] == "Keysight":
                for ch in self.params["PSU_Channel"]:
                    self.results = NewLoadRegulation.executeCV_LoadRegulation(self, self.dict)
                    os.system('cls')
                    datatoCSV_LoadRegulation(self.results, self.params)

        #Transient Recovery
        if self.checkbox_states.get("TransientRecovery"):
            if self.checkbox_states["SpecialCase"]:
                RiseFallTime.executeC(self, self.dict)

            if self.checkbox_states["NormalCase"]:
                RiseFallTime.executeC(self, self.dict)

        #OVP Accuracy Test
        if self.checkbox_states.get("OVP_Test"):
            self.results = OVP_Test.Execute_OVP(self,self.dict)
            os.system('cls')
            datatoCSV_OVP_Accuracy(self.results, self.params)

        #Voltage Line RegulationW
        if self.checkbox_states.get("VoltageLineRegulation"):
            self.results = LineRegulation.executeCV_LoadRegulation(self, self.dict)
            #os.system('cls')
            datatoCSV_Line_Regulation(self.results, self.params)

        #Programming Responses
        if self.checkbox_states.get("ProgrammingSpeed"):
            test = ProgrammingResponse()
            self.results, self.currenttime = test.execute(self.dict)
            os.system('cls')
            datatoCSV_Programming_Response(self.results,self.currenttime,self.params)

    def _run_hornbill_current_tests(self, loop_index):
        x = loop_index
        #Current Accuracy Test
        if self.checkbox_states.get("CurrentAccuracy"):
            if self.checkbox_states.get("CurrentAccuracy_20A_Range"):
                if self.dict["Instrument"] == "Keysight":
                    for ch in self.params["PSU_Channel"]:
                        (infoList,
                        dataList,
                        dataList2) = NewCurrentMeasurement.executeCurrentMeasurementA(self, self.dict, ch)

                        #Measurement Completion
                        if x == (int(self.params["noofloop"]) - 1):
                            self.progress.emit("✅Measurement is complete !")

                            #Export Data to CSV
                            if self.checkbox_states["DataReport"]:

                                #Export data to CSV and Graph (Refer data.py for details)
                                instrumentData(self.params["PSU"], self.params["DMM"], self.params["ELoad"])
                                datatoCSV_Accuracy2(infoList, dataList, dataList2)
                                datatoGraph2(infoList, dataList,dataList2)
                                datatoGraph2.scatterCompareCurrent2(self, float(self.params["Programming_Error_Gain"]), float(self.params["Programming_Error_Offset"]), float(self.params["Readback_Error_Gain"]), float(self.params["Readback_Error_Offset"]), str(self.params["unit"]), float(self.params["I_Rating"]))

                                self._write_config_csv("config.csv")

                                #Read error,config and instrumentData files, then combine to (self.params.unit) file (Refer xlreport for details)
                                A = xlreport(save_directory=self.params["savelocation"], file_name=str(self.params["unit"]))
                                A.run()
                                self.progress.emit("Excel Report Saved: " + str(self.params["savedir"]))
                                self.progress.emit("")

                        if self.force_exit:
                            self.progress.emit("Operation aborted")
                            return  # Exit immediately
            elif self.checkbox_states.get("CurrentAccuracy_2A_Range"):
                if self.dict["Instrument"] == "Keysight":
                    for ch in self.params["PSU_Channel"]:
                        (infoList,
                        dataList,
                        dataList2) = NewCurrentMeasurement.executeCurrentMeasurementA(self, self.dict, ch)

                        #Measurement Completion
                        if x == (int(self.params["noofloop"]) - 1):
                            self.progress.emit("✅Measurement is complete !")

                            #Export Data to CSV
                            if self.checkbox_states["DataReport"]:

                                #Export data to CSV and Graph (Refer data.py for details)
                                instrumentData(self.params["PSU"], self.params["DMM"], self.params["ELoad"])
                                datatoCSV_Accuracy2(infoList, dataList, dataList2)
                                datatoGraph2(infoList, dataList,dataList2)
                                datatoGraph2.scatterCompareCurrent2(self, float(self.params["Programming_Error_Gain"]), float(self.params["Programming_Error_Offset"]), float(self.params["Readback_Error_Gain"]), float(self.params["Readback_Error_Offset"]), str(self.params["unit"]), float(self.params["I_Rating"]))

                                self._write_config_csv("config.csv")

                                #Read error,config and instrumentData files, then combine to (self.params.unit) file (Refer xlreport for details)
                                A = xlreport(save_directory=self.params["savelocation"], file_name=str(self.params["unit"]))
                                A.run()
                                self.progress.emit("Excel Report Saved: " + str(self.params["savedir"]))
                                self.progress.emit("")

                        if self.force_exit:
                            self.progress.emit("Operation aborted")
                            return  # Exit immediately
            elif self.checkbox_states.get("CurrentAccuracy_200mA_Range"):
                if self.dict["Instrument"] == "Keysight":
                    for ch in self.params["PSU_Channel"]:
                        (infoList,
                        dataList,
                        dataList2) = NewCurrentMeasurement.executeCurrentMeasurementA(self, self.dict, ch)

                        #Measurement Completion
                        if x == (int(self.params["noofloop"]) - 1):
                            self.progress.emit("✅Measurement is complete !")

                            #Export Data to CSV
                            if self.checkbox_states["DataReport"]:

                                #Export data to CSV and Graph (Refer data.py for details)
                                instrumentData(self.params["PSU"], self.params["DMM"], self.params["ELoad"])
                                datatoCSV_Accuracy2(infoList, dataList, dataList2)
                                datatoGraph2(infoList, dataList,dataList2)
                                datatoGraph2.scatterCompareCurrent2(self, float(self.params["Programming_Error_Gain"]), float(self.params["Programming_Error_Offset"]), float(self.params["Readback_Error_Gain"]), float(self.params["Readback_Error_Offset"]), str(self.params["unit"]), float(self.params["I_Rating"]))

                                self._write_config_csv("config.csv")

                                #Read error,config and instrumentData files, then combine to (self.params.unit) file (Refer xlreport for details)
                                A = xlreport(save_directory=self.params["savelocation"], file_name=str(self.params["unit"]))
                                A.run()
                                self.progress.emit("Excel Report Saved: " + str(self.params["savedir"]))
                                self.progress.emit("")

                        if self.force_exit:
                            self.progress.emit("Operation aborted")
                            return  # Exit immediately
            elif self.checkbox_states.get("CurrentAccuracy_20mA_Range"):
                if self.dict["Instrument"] == "Keysight":
                    for ch in self.params["PSU_Channel"]:
                        (infoList,
                        dataList,
                        dataList2) = NewCurrentMeasurement.executeCurrentMeasurementA(self, self.dict, ch)

                        #Measurement Completion
                        if x == (int(self.params["noofloop"]) - 1):
                            self.progress.emit("✅Measurement is complete !")

                            #Export Data to CSV
                            if self.checkbox_states["DataReport"]:

                                #Export data to CSV and Graph (Refer data.py for details)
                                instrumentData(self.params["PSU"], self.params["DMM"], self.params["ELoad"])
                                datatoCSV_Accuracy2(infoList, dataList, dataList2)
                                datatoGraph2(infoList, dataList,dataList2)
                                datatoGraph2.scatterCompareCurrent2(self, float(self.params["Programming_Error_Gain"]), float(self.params["Programming_Error_Offset"]), float(self.params["Readback_Error_Gain"]), float(self.params["Readback_Error_Offset"]), str(self.params["unit"]), float(self.params["I_Rating"]))

                                self._write_config_csv("config.csv")

                                #Read error,config and instrumentData files, then combine to (self.params.unit) file (Refer xlreport for details)
                                A = xlreport(save_directory=self.params["savelocation"], file_name=str(self.params["unit"]))
                                A.run()
                                self.progress.emit("Excel Report Saved: " + str(self.params["savedir"]))
                                self.progress.emit("")

                        if self.force_exit:
                            self.progress.emit("Operation aborted")
                            return  # Exit immediately
            elif self.checkbox_states.get("CurrentAccuracy_2mA_Range"):
                if self.dict["Instrument"] == "Keysight":
                    for ch in self.params["PSU_Channel"]:
                        (infoList,
                        dataList,
                        dataList2) = HornbillCurrentMeasurementwithELoad_IMON_2mA.Execute_Current_Accuracy_Current_Static(self, self.dict, ch)

                        #Measurement Completion
                        if x == (int(self.params["noofloop"]) - 1):
                            self.progress.emit("✅Measurement is complete !")

                            #Export Data to CSV
                            if self.checkbox_states["DataReport"]:

                                #Export data to CSV and Graph (Refer data.py for details)
                                instrumentData(self.params["PSU"], self.params["DMM"], self.params["ELoad"])
                                datatoCSV_Accuracy2(infoList, dataList, dataList2)
                                datatoGraph2(infoList, dataList,dataList2)
                                datatoGraph2.scatterCompareCurrent2(self, float(self.params["Programming_Error_Gain"]), float(self.params["Programming_Error_Offset"]), float(self.params["Readback_Error_Gain"]), float(self.params["Readback_Error_Offset"]), str(self.params["unit"]), float(self.params["I_Rating"]))

                                self._write_config_csv("config.csv")

                                #Read error,config and instrumentData files, then combine to (self.params.unit) file (Refer xlreport for details)
                                A = xlreport(save_directory=self.params["savelocation"], file_name=str(self.params["unit"]))
                                A.run()
                                self.progress.emit("Excel Report Saved: " + str(self.params["savedir"]))
                                self.progress.emit("")

                        if self.force_exit:
                            self.progress.emit("Operation aborted")
                            return  # Exit immediately
            elif self.checkbox_states.get("CurrentAccuracy_200uA_Range"):
                if self.dict["Instrument"] == "Keysight":
                    for ch in self.params["PSU_Channel"]:
                        (infoList,
                        dataList,
                        dataList2) = HornbillCurrentMeasurementwithELoad_IMON_200uA.Execute_Current_Accuracy_Current_Static(self, self.dict, ch)

                        #Measurement Completion
                        if x == (int(self.params["noofloop"]) - 1):
                            self.progress.emit("✅Measurement is complete !")

                            #Export Data to CSV
                            if self.checkbox_states["DataReport"]:

                                #Export data to CSV and Graph (Refer data.py for details)
                                instrumentData(self.params["PSU"], self.params["DMM"], self.params["ELoad"])
                                datatoCSV_Accuracy2(infoList, dataList, dataList2)
                                datatoGraph2(infoList, dataList,dataList2)
                                datatoGraph2.scatterCompareCurrent2(self, float(self.params["Programming_Error_Gain"]), float(self.params["Programming_Error_Offset"]), float(self.params["Readback_Error_Gain"]), float(self.params["Readback_Error_Offset"]), str(self.params["unit"]), float(self.params["I_Rating"]))

                                self._write_config_csv("config.csv")

                                #Read error,config and instrumentData files, then combine to (self.params.unit) file (Refer xlreport for details)
                                A = xlreport(save_directory=self.params["savelocation"], file_name=str(self.params["unit"]))
                                A.run()
                                self.progress.emit("Excel Report Saved: " + str(self.params["savedir"]))
                                self.progress.emit("")

                        if self.force_exit:
                            self.progress.emit("Operation aborted")
                            return  # Exit immediately

        #Current Load Regulation Test
        if self.checkbox_states.get("CurrentLoadRegulation"):
            if self.params["Instrument"] == "Keysight":
                for ch in self.params["PSU_Channel"]:
                    self.results = NewLoadRegulation.executeCC_LoadRegulation(self, self.dict)
                    os.system('cls')
                    datatoCSV_LoadRegulation(self.results, self.params)

        #Power Accuracy Test
        if self.checkbox_states.get("PowerAccuracy"):
            if self.checkbox_states["Voltage_Test"]:
                infoList, dataList, dataList2 = PowerMeasurement.executePowerMeasurementB(self, self.dict)  # Power CC

            elif self.checkbox_states["Current_Test"]:
                infoList, dataList, dataList2 = PowerMeasurement.executePowerMeasurementA(self, self.dict)  # Power CV

            #Measurement Completion
            if x == (int(self.params["noofloop"]) - 1):
                self.progress.emit("✅Measurement is complete !")

                #Export Data to CSV
                if self.checkbox_states["DataReport"]:

                    #Export data to CSV and Graph (Refer data.py for details)
                    powerinstrumentData(self.params["PSU"], self.params["DMM"], self.params["DMM2"], self.params["ELoad"])
                    datatoCSV_PowerAccuracy(infoList, dataList, dataList2)
                    datatoGraph3(infoList, dataList,dataList2)
                    datatoGraph3.scatterComparePower(self, float(self.params["Power_Programming_Error_Gain"]), float(self.params["Power_Programming_Error_Offset"]), float(self.params["Power_Readback_Error_Gain"]), float(self.params["Power_Readback_Error_Offset"]), str(self.params["setFunction"]), float(self.params["P_Rating"]))

                    self._write_config_csv("powerconfig.csv")

                    self._save_power_report()

        #Current Line Regulation
        if self.checkbox_states.get("CurrentLineRegulation"):
            self.results = LineRegulation.executeCC_LoadRegulation(self, self.dict)
            datatoCSV_Line_Regulation(self.results, self.params)

        #OCP Accuracy Test
        if self.checkbox_states.get("OCP_Test"):

            #Accuracy Test 1st
            #OCP_test = OCP_Accuracy()
            #self.results = OCP_test.Execute_OCP(dict)
            #os.system('cls')
            # OCP_data_export = datatoCSV_OCP_Test(params)
            #OCP_data_export.AccuracyTest(self.results)

            self.results =[]

            #Activation Time Test
            OCP_test2 = OCP_Activation_Time()
            self.results = OCP_test2.Execute_OCP(self.dict)
            OCP_data_export2 = datatoCSV_OCP_Test(self.params)
            OCP_data_export2.ActivationTime(self.results)

        #Peak Power Test
        if self.checkbox_states.get("Peak_Power_Test"):
            if self.checkbox_states["Voltage_Test"]:
                infoList, dataList, dataList2 = PowerMeasurement.executePowerMeasurementB(self, self.dict)  # Power CC

            elif self.checkbox_states["Current_Test"]:
                infoList, dataList, dataList2 = PowerMeasurement.executePowerMeasurementA(self, self.dict)  # Power CV

            #Measurement Completion
            if x == (int(self.params["noofloop"]) - 1):
                self.progress.emit("✅Measurement is complete !")

                #Export Data to CSV
                if self.checkbox_states["DataReport"]:

                    #Export data to CSV and Graph (Refer data.py for details)
                    powerinstrumentData(self.params["PSU"], self.params["DMM"], self.params["DMM2"], self.params["ELoad"])
                    datatoCSV_PowerAccuracy(infoList, dataList, dataList2)
                    datatoGraph3(infoList, dataList,dataList2)
                    datatoGraph3.scatterComparePower(self, float(self.params["Power_Programming_Error_Gain"]), float(self.params["Power_Programming_Error_Offset"]), float(self.params["Power_Readback_Error_Gain"]), float(self.params["Power_Readback_Error_Offset"]), str(self.params["setFunction"]), float(self.params["P_Rating"]))

                    self._write_config_csv("powerconfig.csv")

                    self._save_power_report()

    def run(self):
        cancelled = False
        failed = False
        selected_tests = [
            name for name, selected in self.checkbox_states.items() if selected
        ]
        instrument_roles = {}
        for role in ("PSU", "DMM", "DMM2", "ELoad", "ACSource", "OSC"):
            address = self.dict.get(role)
            if address:
                instrument_roles[str(address)] = role
        diagnostic_context = {
            "dut": self.params.get("DUT"),
            "test": selected_tests,
            "instrument_roles": instrument_roles,
        }
        self._set_state(TestState.RUNNING)
        set_execution_worker(self)
        set_diagnostic_context(**diagnostic_context)
        try:
            if self.run_context:
                self.run_context.activate_data_paths()
            begin_visa_session_scope()
            for x in range (int(self.params["noofloop"])):
                self.checkpoint()
                #Execute Voltage Measurement for each test checked---------------
                #Voltage Accuracy Test
                self._dispatch_dut_tests(x)
                if self.force_exit:
                    return

                
                                    
        except TestCancelled:
            cancelled = True
            self.progress.emit("Test stopped by operator. Disabling instrument outputs...")
        except Exception as e:
            failed = True
            tb = traceback.format_exc()
            normalized_error = normalize_execution_error(
                e,
                tb,
                dut=self.params.get("DUT"),
                test=selected_tests,
            )
            self.error.emit(normalized_error, tb)
        finally:
            self.close_visa_sessions()
            self.safe_shutdown()
            clear_execution_worker()
            clear_diagnostic_context()
            if failed:
                self._set_state(TestState.FAILED)
            elif cancelled or self.was_aborted:
                self._set_state(TestState.ABORTED)
                self.aborted.emit()
            else:
                self._set_state(TestState.COMPLETED)
                self.finished.emit()

