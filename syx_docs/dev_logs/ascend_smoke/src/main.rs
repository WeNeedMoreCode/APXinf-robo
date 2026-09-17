//! Stage-2 smoke: hand-written ACL FFI, no bindgen / no clang dependency.
//!
//! Proves the minimum stage-2 (Rust apxinf-ascend) ground truth on 310P3:
//! cargo can link libascendcl.so and the aclrt* runtime round-trips device
//! memory from Rust. Every step prints its ACL return code; ACL_SUCCESS = 0.
//!
//! Run (server container):
//!   cd /data/apxinf/ascend_smoke
//!   export ASCEND_RT_VISIBLE_DEVICES=5   # pick a free chip
//!   LD_LIBRARY_PATH=/usr/local/Ascend/ascend-toolkit/latest/lib64:$LD_LIBRARY_PATH \
//!     cargo run --release

use std::ffi::c_void;

// acl_base.h / acl_rt.h, CANN 8.5.1. aclError is int32; enums pass as i32/u32.
extern "C" {
    fn aclInit(configPath: *const i8) -> i32;
    fn aclFinalize() -> i32;
    fn aclrtSetDevice(deviceId: i32) -> i32;
    fn aclrtResetDevice(deviceId: i32) -> i32;
    fn aclrtGetDevice(deviceId: *mut i32) -> i32;
    fn aclrtMalloc(devPtr: *mut *mut c_void, size: usize, policy: u32) -> i32;
    fn aclrtFree(devPtr: *mut c_void) -> i32;
    fn aclrtMemcpy(dst: *mut c_void, destMax: usize, src: *const c_void, count: usize, kind: u32) -> i32;
}

// aclrtMemcpyKind: HOST_TO_HOST=0, HOST_TO_DEVICE=1, DEVICE_TO_HOST=2, D2D=3
const H2D: u32 = 1;
const D2H: u32 = 2;
// aclrtMemMallocPolicy: ACL_MEM_MALLOC_HUGE_FIRST = 0
const HUGE_FIRST: u32 = 0;

fn step(name: &str, code: i32) {
    println!("step {:<10} ret={}", name, code);
    if code != 0 {
        eprintln!("FAILED at {} with aclError {}", name, code);
        std::process::exit(1);
    }
}

fn main() {
    println!("== apxinf-ascend stage-2 smoke: aclrt FFI round-trip ==");

    let dev_id: i32 = 0; // logical chip under ASCEND_RT_VISIBLE_DEVICES

    unsafe {
        step("aclInit", aclInit(std::ptr::null()));
        step("aclrtSetDevice", aclrtSetDevice(dev_id));
        let mut cur: i32 = -1;
        step("aclrtGetDevice", aclrtGetDevice(&mut cur));
        println!("device in use: {}", cur);

        // 4 KiB device allocation + host->device->host round-trip.
        const BYTES: usize = 4096;
        let mut dev_ptr: *mut c_void = std::ptr::null_mut();
        step("aclrtMalloc", aclrtMalloc(&mut dev_ptr, BYTES, HUGE_FIRST));
        println!("device ptr: {:p}", dev_ptr);

        let send: Vec<u8> = (0..BYTES as u32).map(|i| (i % 251) as u8).collect();
        let mut back = vec![0u8; BYTES];
        step("memcpy H2D", aclrtMemcpy(dev_ptr, BYTES, send.as_ptr() as *const c_void, BYTES, H2D));
        step("memcpy D2H", aclrtMemcpy(back.as_mut_ptr() as *mut c_void, BYTES, dev_ptr, BYTES, D2H));

        let mismatches = send.iter().zip(&back).filter(|(a, b)| a != b).count();
        println!("byte mismatches: {}", mismatches);
        if mismatches != 0 {
            eprintln!("FAILED: device memory round-trip corrupted data");
            std::process::exit(1);
        }

        step("aclrtFree", aclrtFree(dev_ptr));
        step("aclrtResetDevice", aclrtResetDevice(dev_id));
        step("aclFinalize", aclFinalize());
    }

    println!("SMOKE_OK: Rust <-> libascendcl.so link + aclrt round-trip verified");
}
