import threading
import unittest

from SCPI_Library.session_manager import (
    begin_visa_session_scope,
    close_visa_session_scope,
    get_visa_resource,
)
from tests.fakes import FakeVisaManager


class VisaSessionManagerTests(unittest.TestCase):
    def tearDown(self):
        close_visa_session_scope()

    def test_reuses_address_and_defers_lease_close(self):
        events = []
        manager = FakeVisaManager(events)
        begin_visa_session_scope(lambda: manager)

        first = get_visa_resource("PSU", 1000)
        second = get_visa_resource("PSU", 2000)
        dmm = get_visa_resource("DMM", 3000)

        self.assertIs(first, second)
        self.assertIsNot(first, dmm)
        self.assertEqual(manager.open_count, 2)
        self.assertEqual(first.timeout, 2000)

        first.close()
        first.write("VOLT 1")
        self.assertNotIn(("resource_close", "PSU"), events)

        failures = close_visa_session_scope()
        self.assertEqual(failures, ())
        self.assertEqual(events.count(("resource_close", "PSU")), 1)
        self.assertEqual(events.count(("resource_close", "DMM")), 1)
        self.assertEqual(events[-1], ("manager_close",))

    def test_reports_close_failure_and_closes_remaining_resources(self):
        events = []
        manager = FakeVisaManager(events, close_fails={"PSU"})
        begin_visa_session_scope(lambda: manager)
        get_visa_resource("PSU")
        get_visa_resource("DMM")

        failures = close_visa_session_scope()

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].address, "PSU")
        self.assertIn(("resource_close", "DMM"), events)
        self.assertEqual(events[-1], ("manager_close",))

    def test_session_scope_is_thread_local(self):
        main_manager = FakeVisaManager()
        begin_visa_session_scope(lambda: main_manager)
        get_visa_resource("PSU")
        thread_open_counts = []

        def use_thread_scope():
            manager = FakeVisaManager()
            begin_visa_session_scope(lambda: manager)
            get_visa_resource("PSU")
            close_visa_session_scope()
            thread_open_counts.append(manager.open_count)

        thread = threading.Thread(target=use_thread_scope)
        thread.start()
        thread.join()

        self.assertEqual(main_manager.open_count, 1)
        self.assertEqual(thread_open_counts, [1])


if __name__ == "__main__":
    unittest.main()
