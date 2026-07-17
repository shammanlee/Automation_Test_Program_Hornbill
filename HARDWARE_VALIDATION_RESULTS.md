# Hardware Validation Record

Complete this record only with the intended DUT and physical instruments. Simulation
results are not acceptable hardware-validation evidence.

## Release Candidate

- Commit:
- Branch or release:
- Date and time:
- Operator:
- Workstation:
- VISA backend/version:
- Result folder:

## Instrument Inventory

| Role | Manufacturer | Model | Serial Number | Firmware | VISA Address |
| --- | --- | --- | --- | --- | --- |
| PSU |  |  |  |  |  |
| DMM |  |  |  |  |  |
| DMM2 |  |  |  |  |  |
| ELoad |  |  |  |  |  |
| Oscilloscope |  |  |  |  |  |
| AC Source |  |  |  |  |  |

## Safety Results

| Scenario | Outputs Disabled | Sessions Closed | GUI Responsive | Diagnostics Saved | Result |
| --- | --- | --- | --- | --- | --- |
| Normal completion |  |  |  |  |  |
| Operator abort |  |  |  |  |  |
| VISA timeout |  |  |  |  |  |
| Instrument disconnect |  |  |  |  |  |
| Report failure |  |  |  |  |  |
| Application restart |  |  |  |  |  |

## DUT Test Matrix

| DUT | Mode | Measurement | Pause/Resume | Abort | Complete | Report | Result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Dolphin | Voltage |  |  |  |  |  |  |
| Dolphin | Current |  |  |  |  |  |  |
| Hornbill | Voltage |  |  |  |  |  |  |
| Hornbill | Current |  |  |  |  |  |  |

## Interrupted-Run Recovery

1. Start a run with at least two loops.
2. Allow the first loop to complete, then terminate the application during the next
   loop only after manually confirming a safe test condition.
3. Restart the application and verify the row is `Interrupted` and does not start.
4. Confirm the previous artifact directory is displayed.
5. Select **Retry Failed**, then **Run Queue**.
6. Verify the retry starts at the next fully completed loop and produces a new run
   directory with its own diagnostics and report artifacts.

Result:

## Deviations and Evidence

- Deviations:
- Diagnostic files:
- Screenshots or photographs:
- Issues created:
- Final approval:
