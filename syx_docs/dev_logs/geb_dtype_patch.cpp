
// GEB_NORM32 追加（2026-09-22）：DataType 类型 attr——字符串走 ParseDtype
// （Cast.dst_type；int 值猜测版编译 rc=-7，proto 枚举序不可拍脑袋）
extern "C" int geb_set_attr_dtype(const char *op_name, const char *attr, const char *dtype) {
    GebModel *m = Cur();
    if (m == nullptr) {
        return -1;
    }
    ge::Operator *op = FindOp(*m, op_name, "set_attr_dtype");
    if (op == nullptr) {
        return -2;
    }
    ge::DataType dt;
    if (!ParseDtype(dtype, dt)) {
        return -3;
    }
    (void)op->SetAttr(std::string(attr), dt);
    return 0;
}
