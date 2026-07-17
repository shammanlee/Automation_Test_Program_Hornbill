"""Voltage test orchestration for production DUT runs."""

import os

from data import (
    datatoCSV_Accuracy,
    datatoCSV_Line_Regulation,
    datatoCSV_LoadRegulation,
    datatoCSV_OVP_Accuracy,
    datatoCSV_Programming_Response,
    datatoGraph,
    instrumentData,
)
from xlreport import xlreport
from DUT_Test_Scripts.DUT_Test import NewVoltageMeasurement
from DUT_Test_Scripts.Dolphin_DUT_Test_No_ELoad_No_DMM import (
    LineRegulation,
    NewLoadRegulation,
    OVP_Test,
    ProgrammingResponse,
    RiseFallTime,
)
from DUT_Test_Scripts.Hornbill_DUT_Test_With_ELoad import (
    HornbillVoltageMeasurementwithELoad,
)
from SCPI_Library.simulation import is_simulation_mode


DOLPHIN_VOLTAGE_ACCURACY_RUNNERS = {
    "CurrentStatic(VoltageChange)": (
        NewVoltageMeasurement.Execute_Voltage_Accuracy_Current_Static
    ),
    "CurrentChange(LoadChange)": (
        NewVoltageMeasurement.Execute_Voltage_Accuracy_Current_Change
    ),
}

HORNBILL_VOLTAGE_ACCURACY_RUNNERS = {
    "CurrentStatic(VoltageChange)": (
        HornbillVoltageMeasurementwithELoad.Execute_Voltage_Accuracy_Current_Static
    ),
    "CurrentChange(LoadChange)": (
        HornbillVoltageMeasurementwithELoad.Execute_Voltage_Accuracy_Current_Change
    ),
    "CurrentStatic(VoltageChange) with Oscilloscope": (
        HornbillVoltageMeasurementwithELoad.Execute_Voltage_Accuracy_Current_Change
    ),
}


class VoltageTestExecutor:
    def __init__(self, worker):
        self.worker = worker

    def run_dolphin(self, loop_index):
        self.worker.checkpoint()
        if self.run_dolphin_accuracy(loop_index):
            return

        self.worker.checkpoint()
        self.run_auxiliary()
        self.worker.checkpoint()

    def run_hornbill(self, loop_index):
        self.worker.checkpoint()
        if self.run_hornbill_accuracy(loop_index):
            return

        self.worker.checkpoint()
        self.run_auxiliary()
        self.worker.checkpoint()

    def run_auxiliary(self):
        worker = self.worker
        worker.checkpoint()

        if worker.checkbox_states.get("VoltageLoadRegulation"):
            if worker.params["Instrument"] == "Keysight":
                for _channel in worker.params["PSU_Channel"]:
                    worker.results = worker._execute_checkpointed(
                        NewLoadRegulation.executeCV_LoadRegulation,
                        worker,
                        worker.dict,
                    )
                    os.system("cls")
                    worker._execute_checkpointed(
                        datatoCSV_LoadRegulation,
                        worker.results,
                        worker.params,
                    )

        if worker.checkbox_states.get("TransientRecovery"):
            if worker.checkbox_states["SpecialCase"]:
                worker._execute_checkpointed(
                    RiseFallTime.executeC,
                    worker,
                    worker.dict,
                )

            if worker.checkbox_states["NormalCase"]:
                worker._execute_checkpointed(
                    RiseFallTime.executeC,
                    worker,
                    worker.dict,
                )

        if worker.checkbox_states.get("OVP_Test"):
            worker.results = worker._execute_checkpointed(
                OVP_Test.Execute_OVP,
                worker,
                worker.dict,
            )
            os.system("cls")
            worker._execute_checkpointed(
                datatoCSV_OVP_Accuracy,
                worker.results,
                worker.params,
            )

        if worker.checkbox_states.get("VoltageLineRegulation"):
            worker.results = worker._execute_checkpointed(
                LineRegulation.executeCV_LoadRegulation,
                worker,
                worker.dict,
            )
            worker._execute_checkpointed(
                datatoCSV_Line_Regulation,
                worker.results,
                worker.params,
            )

        if worker.checkbox_states.get("ProgrammingSpeed"):
            test = ProgrammingResponse()
            worker.results, worker.currenttime = worker._execute_checkpointed(
                test.execute,
                worker.dict,
            )
            os.system("cls")
            worker._execute_checkpointed(
                datatoCSV_Programming_Response,
                worker.results,
                worker.currenttime,
                worker.params,
            )

        worker.checkpoint()

    def run_dolphin_accuracy(self, loop_index):
        return self.run_selected_accuracy(
            loop_index,
            DOLPHIN_VOLTAGE_ACCURACY_RUNNERS,
        )

    def run_hornbill_accuracy(self, loop_index):
        return self.run_selected_accuracy(
            loop_index,
            HORNBILL_VOLTAGE_ACCURACY_RUNNERS,
        )

    def run_selected_accuracy(self, loop_index, runners):
        worker = self.worker
        if not worker.checkbox_states.get("VoltageAccuracy"):
            return False
        if worker.dict["Instrument"] != "Keysight":
            return False

        runner = self.selected_accuracy_runner(runners)
        if runner is None:
            return False

        return self.run_accuracy(loop_index, runner)

    def selected_accuracy_runner(self, runners):
        for selection, runner in runners.items():
            if self.worker.checkbox_states.get(selection):
                return runner
        return None

    def run_accuracy(self, loop_index, runner):
        worker = self.worker
        for channel in worker.params["PSU_Channel"]:
            info_list, data_list, readback_list = worker._execute_checkpointed(
                runner,
                worker,
                worker.dict,
                channel,
                worker=worker,
            )
            if loop_index == int(worker.params["noofloop"]) - 1:
                worker.progress.emit("✅Measurement is complete !")
                if worker.checkbox_states["DataReport"]:
                    self.export_accuracy(
                        info_list,
                        data_list,
                        readback_list,
                    )

            if worker.force_exit:
                worker.progress.emit("Operation aborted")
                return True

        return False

    def export_accuracy(
        self,
        info_list,
        data_list,
        readback_list,
    ):
        worker = self.worker
        worker._execute_checkpointed(
            instrumentData,
            worker.params["PSU"],
            worker.params["DMM"],
            worker.params["ELoad"],
        )
        worker._execute_checkpointed(
            datatoCSV_Accuracy,
            info_list,
            data_list,
            readback_list,
        )
        worker._execute_checkpointed(
            datatoGraph,
            info_list,
            data_list,
            readback_list,
        )
        worker._execute_checkpointed(
            datatoGraph.scatterCompareVoltage,
            worker,
            float(worker.params["Programming_Error_Gain"]),
            float(worker.params["Programming_Error_Offset"]),
            float(worker.params["Readback_Error_Gain"]),
            float(worker.params["Readback_Error_Offset"]),
            str(worker.params["unit"]),
            float(worker.params["Voltage_Rating"]),
        )
        worker._execute_checkpointed(worker._write_config_csv, "config.csv")
        worker._execute_checkpointed(self.save_report)

    def save_report(self):
        worker = self.worker
        file_name = str(worker.params["unit"])
        if is_simulation_mode():
            file_name = f"SIMULATED_{file_name}"
        report = xlreport(
            save_directory=worker.params["savelocation"],
            file_name=file_name,
        )
        report.run()
        worker.progress.emit(
            "Excel Report Saved: " + str(worker.params["savelocation"])
        )
        worker.progress.emit("")
