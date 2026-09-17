fn main() {
    println!("cargo:rustc-link-search=native=/usr/local/Ascend/ascend-toolkit/latest/lib64");
    println!("cargo:rustc-link-lib=dylib=ascendcl");
}
