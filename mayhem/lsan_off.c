/* Leak detection is off at build time: leaks are not the defect class this fuzzing targets. */
int __lsan_is_turned_off(void) { return 1; }
