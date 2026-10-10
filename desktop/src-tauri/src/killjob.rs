//! Children die with us: however this process ends (window closed, crash, `Stop-Process -Force`, Task Manager),
//! the processes it started (the Python backend, a uv download, and everything *they* started) end too.
//!
//! Why this is needed: on Windows a child process does not end when its parent does, and the usual Rust safety nets
//! do not run at exit - tao calls `std::process::exit` right after `RunEvent::Exit`, so destructors and tokio's
//! `kill_on_drop` never run, and a forced kill runs nothing at all. Without this a crashed desktop app leaves the
//! Python backend holding its port, and a closed window may leave uv downloading gigabytes.
//!
//! Windows: one Job Object per process, created on first use with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Every child
//! is assigned to it right after it is spawned (`adopt`); its own children join the job automatically. The job
//! handle is never closed by us: the kernel closes it when this process ends - for any reason - and that kills every
//! process in the job. (A child could start a grandchild in the microseconds between spawn and `adopt`; darkroom's
//! children do not do that before their first line of Python / uv runs.)
//!
//! Linux: `PR_SET_PDEATHSIG(SIGKILL)` in the child before exec (`die_with_parent`), so the kernel kills it when the
//! thread that spawned it - in practice this process - ends. macOS has neither; there the normal exit path
//! (`backend::stop`, kill_on_drop) is all there is.
//!
//! This file is also compiled into the `darkroom` CLI launcher (`desktop/cli/src/main.rs`, `#[path]`), which has no
//! dependencies on purpose; so it uses only `std` and declares the few kernel32 / libc functions itself.

#[cfg(windows)]
mod imp {
    use std::ffi::c_void;
    use std::os::windows::io::RawHandle;
    use std::sync::OnceLock;

    type Handle = *mut c_void;

    /// `JOBOBJECT_BASIC_LIMIT_INFORMATION` (winnt.h); `#[repr(C)]` gives the same padding as the C struct.
    #[repr(C)]
    #[derive(Default)]
    struct BasicLimits {
        per_process_user_time_limit: i64,
        per_job_user_time_limit: i64,
        limit_flags: u32,
        minimum_working_set_size: usize,
        maximum_working_set_size: usize,
        active_process_limit: u32,
        affinity: usize,
        priority_class: u32,
        scheduling_class: u32,
    }

    /// `IO_COUNTERS` (winnt.h).
    #[repr(C)]
    #[derive(Default)]
    struct IoCounters {
        read_operation_count: u64,
        write_operation_count: u64,
        other_operation_count: u64,
        read_transfer_count: u64,
        write_transfer_count: u64,
        other_transfer_count: u64,
    }

    /// `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` (winnt.h).
    #[repr(C)]
    #[derive(Default)]
    struct ExtendedLimits {
        basic: BasicLimits,
        io: IoCounters,
        process_memory_limit: usize,
        job_memory_limit: usize,
        peak_process_memory_used: usize,
        peak_job_memory_used: usize,
    }

    /// `JobObjectExtendedLimitInformation` in the `JOBOBJECTINFOCLASS` enum.
    const EXTENDED_LIMIT_INFORMATION: i32 = 9;
    const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: u32 = 0x2000;

    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn CreateJobObjectW(attributes: *mut c_void, name: *const u16) -> Handle;
        fn SetInformationJobObject(job: Handle, class: i32, info: *mut c_void, len: u32) -> i32;
        fn AssignProcessToJobObject(job: Handle, process: Handle) -> i32;
    }

    /// The process-wide job (its handle as an integer: raw pointers are not `Sync`), or 0 when it could not be made.
    fn job() -> usize {
        static JOB: OnceLock<usize> = OnceLock::new();
        *JOB.get_or_init(|| {
            // SAFETY: documented kernel32 calls with valid arguments; `limits` outlives the call that reads it.
            unsafe {
                let job = CreateJobObjectW(std::ptr::null_mut(), std::ptr::null());
                if job.is_null() {
                    return 0;
                }
                let mut limits = ExtendedLimits::default();
                limits.basic.limit_flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                let ok = SetInformationJobObject(
                    job,
                    EXTENDED_LIMIT_INFORMATION,
                    (&raw mut limits).cast(),
                    size_of::<ExtendedLimits>() as u32,
                );
                if ok == 0 { 0 } else { job as usize }
            }
        })
    }

    /// Puts the process behind `process` into the kill-on-close job. Best effort: false when the job could not be
    /// created or the process could not be assigned (then only the normal exit path stops it).
    pub fn adopt(process: RawHandle) -> bool {
        let job = job();
        if job == 0 || process.is_null() {
            return false;
        }
        // SAFETY: `job` is a live job handle owned by this process for its whole life; `process` is a live process
        // handle owned by the caller's Child.
        unsafe { AssignProcessToJobObject(job as Handle, process as Handle) != 0 }
    }
}

#[cfg(windows)]
pub use imp::adopt;

/// Linux: ask the kernel to SIGKILL this (child) process when its parent dies. Meant for `pre_exec`, so it only
/// makes the one async-signal-safe `prctl` call.
#[cfg(target_os = "linux")]
pub fn die_with_parent() -> std::io::Result<()> {
    unsafe extern "C" {
        fn prctl(option: i32, arg2: u64, arg3: u64, arg4: u64, arg5: u64) -> i32;
    }
    const PR_SET_PDEATHSIG: i32 = 1;
    const SIGKILL: u64 = 9;
    // SAFETY: prctl(PR_SET_PDEATHSIG, SIGKILL) only sets a flag on the calling process.
    if unsafe { prctl(PR_SET_PDEATHSIG, SIGKILL, 0, 0, 0) } == 0 {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error())
    }
}

#[cfg(all(test, windows))]
mod tests {
    #[test]
    fn a_child_is_adopted_into_the_job() {
        use std::os::windows::io::AsRawHandle;
        let mut child = std::process::Command::new("cmd")
            .args(["/c", "ping -n 3 127.0.0.1 >NUL"])
            .spawn()
            .unwrap();
        assert!(super::adopt(child.as_raw_handle()));
        let _ = child.kill();
        let _ = child.wait();
    }
}
