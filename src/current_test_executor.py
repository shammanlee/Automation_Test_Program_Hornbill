"""Current and power test orchestration for production DUT runs."""

import os

from data import (
    datatoCSV_Accuracy2,
    datatoCSV_Line_Regulation,
    datatoCSV_LoadRegulation,
    datatoCSV_OCP_Test,
    datatoCSV_PowerAccuracy,
    datatoGraph2,
    datatoGraph3,
    instrumentData,
    powerinstrumentData,
)
from xlreport import xlreport
from xlreportpower import xlreportpower
from DUT_Test_Scripts.DUT_Test import NewCurrentMeasurement
from DUT_Test_Scripts.Dolphin_DUT_Test_No_ELoad_No_DMM import (
    LineRegulation,
    NewLoadRegulation,
    OCP_Activation_Time,
    PowerMeasurement,
)
from DUT_Test_Scripts.Hornbill_DUT_Test_With_ELoad import (
    HornbillCurrentMeasurementwithELoad_IMON_200uA,
    HornbillCurrentMeasurementwithELoad_IMON_2mA,
)
from SCPI_Library.simulation import is_simulation_mode


HORNBILL_CURRENT_ACCURACY_RUNNERS = {
    "CurrentAccuracy_20A_Range": NewCurrentMeasurement.executeCurrentMeasurementA,
    "CurrentAccuracy_2A_Range": NewCurrentMeasurement.executeCurrentMeasurementA,
    "CurrentAccuracy_200mA_Range": NewCurrentMeasurement.executeCurrentMeasurementA,
    "CurrentAccuracy_20mA_Range": NewCurrentMeasurement.executeCurrentMeasurementA,
    "CurrentAccuracy_2mA_Range": (
        HornbillCurrentMeasurementwithELoad_IMON_2mA.Execute_Current_Accuracy_Current_Static
    ),
    "CurrentAccuracy_200uA_Range": (
        HornbillCurrentMeasurementwithELoad_IMON_200uA.Execute_Current_Accuracy_Current_Static
    ),
}


class CurrentTestExecutor:
    def __init__(self, worker):
        self.worker = worker

    def run_dolphin(self, loop_index):
        worker = self.worker
        worker.checkpoint()
        if self.run_dolphin_accuracy(loop_index):
            return

        worker.checkpoint()
        self.run_auxiliary(loop_index)
        worker.checkpoint()

    def run_hornbill(self, loop_index):
        worker = self.worker
        worker.checkpoint()
        if self.run_hornbill_accuracy(loop_index):
            return

        worker.checkpoint()
        self.run_auxiliary(loop_index)
        worker.checkpoint()
        self.run_power_test(loop_index, "Peak_Power_Test")
        worker.checkpoint()

    def run_auxiliary(self, loop_index):
        worker = self.worker
        worker.checkpoint()

        if worker.checkbox_states.get("CurrentLoadRegulation"):
            if worker.params["Instrument"] == "Keysight":
                for _channel in worker.params["PSU_Channel"]:
                    worker.results = worker._execute_checkpointed(
                        NewLoadRegulation.executeCC_LoadRegulation,
                        worker,
                        worker.dict,
                    )
                    os.system("cls")
                    worker._execute_checkpointed(
                        datatoCSV_LoadRegulation,
                        worker.results,
                        worker.params,
                    )

        self.run_power_test(loop_index, "PowerAccuracy")

        if worker.checkbox_states.get("CurrentLineRegulation"):
            worker.results = worker._execute_checkpointed(
                LineRegulation.executeCC_LoadRegulation,
                worker,
                worker.dict,
            )
            worker._execute_checkpointed(
                datatoCSV_Line_Regulation,
                worker.results,
                worker.params,
            )

        if worker.checkbox_states.get("OCP_Test"):
            worker.results = []
            ocp_test = OCP_Activation_Time()
            worker.results = worker._execute_checkpointed(
                ocp_test.Execute_OCP,
                worker.dict,
            )
            ocp_export = datatoCSV_OCP_Test(worker.params)
            worker._execute_checkpointed(
                ocp_export.ActivationTime,
                worker.results,
            )

        worker.checkpoint()

    def run_power_test(self, loop_index, selection):
        worker = self.worker
        worker.checkpoint()
        if not worker.checkbox_states.get(selection):
            return

        if worker.checkbox_states["Voltage_Test"]:
            info_list, data_list, readback_list = worker._execute_checkpointed(
                PowerMeasurement.executePowerMeasurementB,
                worker,
                worker.dict,
            )
        elif worker.checkbox_states["Current_Test"]:
            info_list, data_list, readback_list = worker._execute_checkpointed(
                PowerMeasurement.executePowerMeasurementA,
                worker,
                worker.dict,
            )

        if loop_index == int(worker.params["noofloop"]) - 1:
            worker.progress.emit("✅Measurement is complete !")
            if worker.checkbox_states["DataReport"]:
                self.export_power_accuracy(
                    info_list,
                    data_list,
                    readback_list,
                )

    def export_power_accuracy(
        self,
        info_list,
        data_list,
        readback_list,
    ):
        worker = self.worker
        worker._execute_checkpointed(
            powerinstrumentData,
            worker.params["PSU"],
            worker.params["DMM"],
            worker.params["DMM2"],
            worker.params["ELoad"],
        )
        worker._execute_checkpointed(
            datatoCSV_PowerAccuracy,
            info_list,
            data_list,
            readback_list,
        )
        worker._execute_checkpointed(
            datatoGraph3,
            info_list,
            data_list,
            readback_list,
        )
        worker._execute_checkpointed(
            datatoGraph3.scatterComparePower,
            worker,
            float(worker.params["Power_Programming_Error_Gain"]),
            float(worker.params["Power_Programming_Error_Offset"]),
            float(worker.params["Power_Readback_Error_Gain"]),
            float(worker.params["Power_Readback_Error_Offset"]),
            str(worker.params["setFunction"]),
            float(worker.params["P_Rating"]),
        )
        worker._execute_checkpointed(worker._write_config_csv, "powerconfig.csv")
        worker._execute_checkpointed(self.save_power_report)

    def run_dolphin_accuracy(self, loop_index):
        worker = self.worker
        if not worker.checkbox_states.get("CurrentAccuracy"):
            return False
        if worker.dict["Instrument"] != "Keysight":
            return False

        return self.run_accuracy(
            loop_index,
            NewCurrentMeasurement.executeCurrentMeasurementA,
        )

    def run_hornbill_accuracy(self, loop_index):
        worker = self.worker
        if not worker.checkbox_states.get("CurrentAccuracy"):
            return False
        if worker.dict["Instrument"] != "Keysight":
            return False

        runner = self.selected_hornbill_accuracy_runner()
        if runner is None:
            return False

        return self.run_accuracy(loop_index, runner)

    def selected_hornbill_accuracy_runner(self):
        for selection, runner in HORNBILL_CURRENT_ACCURACY_RUNNERS.items():
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
            datatoCSV_Accuracy2,
            info_list,
            data_list,
            readback_list,
        )
        worker._execute_checkpointed(
            datatoGraph2,
            info_list,
            data_list,
            readback_list,
        )
        worker._execute_checkpointed(
            datatoGraph2.scatterCompareCurrent2,
            worker,
            float(worker.params["Programming_Error_Gain"]),
            float(worker.params["Programming_Error_Offset"]),
            float(worker.params["Readback_Error_Gain"]),
            float(worker.params["Readback_Error_Offset"]),
            str(worker.params["unit"]),
            float(worker.params["I_Rating"]),
        )
        worker._execute_checkpointed(worker._write_config_csv, "config.csv")

        report = xlreport(
            save_directory=worker.params["savelocation"],
            file_name=str(worker.params["unit"]),
        )
        worker._execute_checkpointed(report.run)
        worker.progress.emit("Excel Report Saved: " + str(worker.params["savedir"]))
        worker.progress.emit("")

    def save_power_report(self):
        worker = self.worker
        file_name = (
            "Power_CV"
            if worker.params["setFunction"] == "Current"
            else "Power_CC"
        )
        if is_simulation_mode():
            file_name = f"SIMULATED_{file_name}"
        report = xlreportpower(
            save_directory=worker.params["savedir"],
            file_name=file_name,
        )
        report.run()
        worker.progress.emit("Excel Report Saved: " + str(worker.params["savedir"]))
        worker.progress.emit("")
