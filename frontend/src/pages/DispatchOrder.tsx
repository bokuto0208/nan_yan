import React, { useEffect, useMemo, useState } from "react";
import * as XLSX from "xlsx";

// ✅ 後端 API
const API_BASE_URL = "http://127.0.0.1:8000/api";

// ====== 型別 ======
type CompletionCreate = {
  completion_no: string;       // 完工單號（唯一）
  completion_date: string;     // 完工日期
  stock_in_date: string;       // 入庫日期
  finished_item_no: string;    // 完工品號
  completed_qty: number;       // 完工數量
  machine_code: string;        // 機台代號
  mold_code: string;           // 模具代號
};

type Completion = CompletionCreate & {
  id?: number;
  created_at?: string;
  updated_at?: string;
};

type BatchResult = {
  inserted: number;
  skipped: number;
  skipped_completion_nos: string[];
};

// ====== 工具：日期格式統一成 YYYY/MM/DD ======
function normalizeDate(v: any): string {
  if (v === null || v === undefined || v === "") return "";

  // Excel 常見：日期是數字（序號）
  if (typeof v === "number") {
    const d = XLSX.SSF.parse_date_code(v);
    if (!d) return "";
    const mm = String(d.m).padStart(2, "0");
    const dd = String(d.d).padStart(2, "0");
    return `${d.y}/${mm}/${dd}`;
  }

  // 字串日期：2025-11-01 / 2025.11.01 / 2025/11/01
  if (typeof v === "string") {
    const s = v.trim().replace(/\./g, "/").replace(/-/g, "/");
    const parts = s.split("/");
    if (parts.length === 3) {
      const y = parts[0];
      const m = String(parseInt(parts[1], 10)).padStart(2, "0");
      const d = String(parseInt(parts[2], 10)).padStart(2, "0");
      if (y && m && d) return `${y}/${m}/${d}`;
    }
    return s;
  }

  return String(v);
}

// ====== 工具：清理欄位名稱（把空白/括號去掉）=====
function cleanHeader(h: string): string {
  return String(h ?? "")
    .replace(/\s+/g, "")
    .replace(/\[|\]|\(|\)/g, "")
    .trim();
}

// ====== 你要的 7 欄：Excel欄位名稱對應 ======
const COL_ALIASES: Record<keyof CompletionCreate, string[]> = {
  completion_date: ["完工日期"],
  stock_in_date: ["入庫日期"],
  finished_item_no: ["完工品號"],
  completed_qty: ["完工數量"],
  completion_no: ["完工單號"],
  machine_code: ["機台代號", "機台代碼"],
  mold_code: ["模具代號", "模具代碼"],
};

// ====== 從 Excel header 找出每個欄位在表格裡的 key ======
function resolveHeaderMap(headers: string[]) {
  const cleaned = headers.map(cleanHeader);
  const map: Partial<Record<keyof CompletionCreate, string>> = {};

  (Object.keys(COL_ALIASES) as (keyof CompletionCreate)[]).forEach((k) => {
    const aliasList = COL_ALIASES[k].map(cleanHeader);
    const idx = cleaned.findIndex((h) => aliasList.includes(h));
    if (idx >= 0) map[k] = headers[idx];
  });

  return map;
}

// ====== 找到真正的欄位列（不一定在第一列）=====
function findHeaderRowIndex(rows2d: any[][]): number {
  // 只要看到這些關鍵欄位任一，就認定是 header row
  const mustContainAny = ["完工日期", "完工單號", "入庫日期"];

  for (let i = 0; i < rows2d.length; i++) {
    const row = rows2d[i] ?? [];
    const cleanedRow = row.map((c) => cleanHeader(String(c ?? "")));
    const hit = mustContainAny.some((kw) => cleanedRow.includes(cleanHeader(kw)));
    if (hit) return i;
  }
  return -1;
}

// ====== API ======
async function apiGetCompletions(): Promise<Completion[]> {
  const res = await fetch(`${API_BASE_URL}/completions`);
  if (!res.ok) throw new Error(`GET /completions failed: ${res.status}`);
  return res.json();
}

async function apiCreateCompletionsBatch(payloads: CompletionCreate[]): Promise<BatchResult> {
  const res = await fetch(`${API_BASE_URL}/completions/batch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payloads),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`POST /completions/batch failed (${res.status}): ${text}`);
  }
  return res.json();
}

// ====== UI: 表格 ======
function SimpleTable({ rows }: { rows: any[] }) {
  const cols = [
    "completion_no",
    "completion_date",
    "stock_in_date",
    "finished_item_no",
    "completed_qty",
    "machine_code",
    "mold_code",
  ];

  const colNames: Record<string, string> = {
    completion_no: "完工單號",
    completion_date: "完工日期",
    stock_in_date: "入庫日期",
    finished_item_no: "完工品號",
    completed_qty: "完工數量",
    machine_code: "機台代號",
    mold_code: "模具代號"
  };

  return (
    <div style={{ 
      overflowX: "auto", 
      borderRadius: 12,
      background: 'rgba(15, 23, 36, 0.6)',
      border: "1px solid rgba(30, 160, 233, 0.2)",
      boxShadow: '0 4px 16px rgba(0, 0, 0, 0.2)'
    }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
        <thead>
          <tr style={{ 
            background: "linear-gradient(135deg, rgba(30, 160, 233, 0.15), rgba(124, 58, 237, 0.1))",
            borderBottom: '2px solid rgba(30, 160, 233, 0.3)'
          }}>
            {cols.map((c) => (
              <th
                key={c}
                style={{
                  textAlign: "left",
                  padding: "14px 16px",
                  color: '#1ea0e9',
                  fontWeight: 700,
                  fontSize: 13,
                  letterSpacing: '0.3px',
                  whiteSpace: "nowrap",
                  textTransform: 'uppercase'
                }}
              >
                {colNames[c] || c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {!rows?.length ? (
            <tr>
              <td colSpan={cols.length} style={{ 
                padding: '32px 16px',
                textAlign: 'center',
                color: 'rgba(230, 238, 248, 0.5)',
                fontSize: 14
              }}>
                📭 尚無資料
              </td>
            </tr>
          ) : (
            rows.map((r, idx) => (
              <tr 
                key={idx} 
                style={{ 
                  borderBottom: "1px solid rgba(30, 160, 233, 0.1)",
                  transition: 'all 0.2s ease',
                  background: idx % 2 === 0 ? 'transparent' : 'rgba(30, 160, 233, 0.03)'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'rgba(30, 160, 233, 0.1)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = idx % 2 === 0 ? 'transparent' : 'rgba(30, 160, 233, 0.03)';
                }}
              >
                {cols.map((c) => (
                  <td key={c} style={{ 
                    padding: "12px 16px",
                    whiteSpace: "nowrap",
                    color: 'rgba(230, 238, 248, 0.9)',
                    fontSize: 13,
                    fontFamily: c === 'completion_no' || c === 'finished_item_no' ? 'monospace' : 'inherit'
                  }}>
                    {String(r?.[c] ?? "")}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export default function DispatchOrderPage() {
  const [fileName, setFileName] = useState("");
  const [previewRows, setPreviewRows] = useState<CompletionCreate[]>([]);
  const [dbRows, setDbRows] = useState<Completion[]>([]);
  const [batchResult, setBatchResult] = useState<BatchResult | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // ✅ 新增：手動輸入用的 state
  const [manualInput, setManualInput] = useState<CompletionCreate>({
    completion_no: "",
    completion_date: "",
    stock_in_date: "",
    finished_item_no: "",
    completed_qty: 0,
    machine_code: "",
    mold_code: "",
  });

  const canImport = useMemo(
    () => previewRows.length > 0 && !loading,
    [previewRows.length, loading]
  );

  const canManualSubmit = useMemo(() => {
    return (
      !loading &&
      manualInput.completion_no.trim() !== "" &&
      manualInput.finished_item_no.trim() !== "" &&
      manualInput.completed_qty !== 0
    );
  }, [manualInput, loading]);

  // 初次載入：抓 DB 已有資料
  useEffect(() => {
    (async () => {
      try {
        const data = await apiGetCompletions();
        setDbRows(data);
      } catch (e: any) {
        setError(e?.message ?? "載入資料庫資料失敗");
      }
    })();
  }, []);

  // ====== 手動輸入：欄位變更 ======
  function handleManualChange<K extends keyof CompletionCreate>(
    key: K,
    value: string
  ) {
    setManualInput((prev) => ({
      ...prev,
      [key]:
        key === "completed_qty"
          ? (value === "" ? 0 : Number(value))
          : value,
    }));
  }

  // ====== 手動輸入：送出 ======
  async function handleManualSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBatchResult(null);
    setLoading(true);

    try {
      const payload: CompletionCreate = {
        completion_no: manualInput.completion_no.trim(),
        completion_date: manualInput.completion_date.trim(),
        stock_in_date: manualInput.stock_in_date.trim(),
        finished_item_no: manualInput.finished_item_no.trim(),
        completed_qty: Number(manualInput.completed_qty) || 0,
        machine_code: manualInput.machine_code.trim(),
        mold_code: manualInput.mold_code.trim(),
      };

      // 簡單必填檢查
      if (!payload.completion_no || !payload.finished_item_no) {
        setError("完工單號、完工品號為必填");
        setLoading(false);
        return;
      }

      const result = await apiCreateCompletionsBatch([payload]);
      setBatchResult(result);

      // 清空欄位
      setManualInput({
        completion_no: "",
        completion_date: "",
        stock_in_date: "",
        finished_item_no: "",
        completed_qty: 0,
        machine_code: "",
        mold_code: "",
      });

      // 更新資料庫畫面
      const data = await apiGetCompletions();
      setDbRows(data);
    } catch (e: any) {
      setError(e?.message ?? "手動新增失敗");
    } finally {
      setLoading(false);
    }
  }

  // ====== 讀 Excel 檔 ======
  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    setError("");
    setBatchResult(null);
    setPreviewRows([]);

    const f = e.target.files?.[0];
    if (!f) return;

    setFileName(f.name);

    try {
      const buf = await f.arrayBuffer();
      const wb = XLSX.read(buf, { type: "array" });

      const sheetName = wb.SheetNames[0];
      const ws = wb.Sheets[sheetName];
      if (!ws) throw new Error("找不到工作表（sheet）");

      // 先讀 2D，為了找出真正 header 在哪一列
      const rows2d: any[][] = XLSX.utils.sheet_to_json(ws, {
        header: 1,
        raw: true,
        defval: "",
      });
      if (!rows2d.length) throw new Error("Excel 是空的");

      const headerRowIndex = findHeaderRowIndex(rows2d);
      if (headerRowIndex === -1) {
        throw new Error(
          "找不到欄位列（需要包含：完工日期 / 入庫日期 / 完工單號 其中之一）\n" +
            "請確認企業提供的 Excel 第一張工作表是否正確。"
        );
      }

      // 取得真正欄位列
      const headers = (rows2d[headerRowIndex] as any[]).map((h) =>
        String(h ?? "").trim()
      );
      const headerMap = resolveHeaderMap(headers);

      // 必備欄位檢查（顯示中文欄位名）
      const required: (keyof CompletionCreate)[] = [
        "completion_date",
        "stock_in_date",
        "finished_item_no",
        "completed_qty",
        "completion_no",
        "machine_code",
        "mold_code",
      ];

      const missing = required.filter((k) => !headerMap[k]);
      if (missing.length) {
        const missingZh = missing
          .map((k) => COL_ALIASES[k][0])
          .join("、");
        throw new Error(
          `Excel 缺少必要欄位：${missingZh}\n` +
            `目前讀到欄位：${headers.join("、")}`
        );
      }

      // ✅ 用 range 從 headerRowIndex 開始，確保資料是跟著正確 header
      const jsonRows: any[] = XLSX.utils.sheet_to_json(ws, {
        range: headerRowIndex,
        header: headers, // 指定 header
        defval: "",
        raw: true,
      });

      // jsonRows[0] 會是 header 那列本身（因為 range 包含 header row）
      // 所以資料從 index 1 開始
      const dataRows = jsonRows.slice(1);

      const picked: CompletionCreate[] = dataRows
        .map((r) => {
          const completion_date = normalizeDate(
            r[headerMap.completion_date!]
          );
          const stock_in_date = normalizeDate(
            r[headerMap.stock_in_date!]
          );
          const finished_item_no = String(
            r[headerMap.finished_item_no!] ?? ""
          ).trim();
          const completion_no = String(
            r[headerMap.completion_no!] ?? ""
          ).trim();
          const machine_code = String(
            r[headerMap.machine_code!] ?? ""
          ).trim();
          const mold_code = String(
            r[headerMap.mold_code!] ?? ""
          ).trim();

          const qtyRaw = r[headerMap.completed_qty!];
          const completed_qty =
            typeof qtyRaw === "number"
              ? qtyRaw
              : parseInt(String(qtyRaw).trim(), 10);

          return {
            completion_no,
            completion_date,
            stock_in_date,
            finished_item_no,
            completed_qty: Number.isFinite(completed_qty)
              ? completed_qty
              : 0,
            machine_code,
            mold_code,
          };
        })
        // 過濾空列（至少要有完工單號、完工品號）
        .filter((x) => x.completion_no && x.finished_item_no);

      if (!picked.length)
        throw new Error(
          "沒有讀到有效資料（可能整張表是空的或欄位不符）"
        );

      setPreviewRows(picked);
    } catch (e: any) {
      setError(e?.message ?? "讀取 Excel 失敗");
    }
  }

  // 匯入資料庫（從 Excel 預覽）
  async function handleImport() {
    setError("");
    setLoading(true);
    setBatchResult(null);

    try {
      const result = await apiCreateCompletionsBatch(previewRows);
      setBatchResult(result);

      // 匯入成功後刷新 DB 資料
      const data = await apiGetCompletions();
      setDbRows(data);
    } catch (e: any) {
      setError(e?.message ?? "匯入失敗");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ padding: 16 }}>
      <h2 style={{ 
        marginBottom: 16, 
        fontSize: 24,
        fontWeight: 700,
        background: 'linear-gradient(135deg, #1ea0e9, #7c3aed)',
        WebkitBackgroundClip: 'text',
        WebkitTextFillColor: 'transparent',
        letterSpacing: '0.5px'
      }}>
        📋 報完工管理
      </h2>

      {/* 🔹 手動輸入區塊 */}
      <div
        style={{
          marginBottom: 24,
          padding: '20px',
          borderRadius: 12,
          background: 'linear-gradient(135deg, rgba(26, 58, 94, 0.4), rgba(15, 40, 71, 0.6))',
          border: '1px solid rgba(255, 255, 255, 0.15)',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.3)',
          backdropFilter: 'blur(10px)'
        }}
      >
        <h3 style={{ 
          marginBottom: 16, 
          fontSize: 16,
          fontWeight: 700,
          color: '#1ea0e9',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          letterSpacing: '0.3px'
        }}>
          <span style={{ fontSize: 20 }}>✏️</span>
          手動新增報完工記錄
        </h3>
        <form
          onSubmit={handleManualSubmit}
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: 12,
            alignItems: "end",
          }}
        >
          <div>
            <label style={{
              display: 'block',
              marginBottom: 6,
              fontSize: 12,
              fontWeight: 600,
              color: 'rgba(230, 238, 248, 0.9)',
              letterSpacing: '0.3px'
            }}>
              完工單號 <span style={{ color: '#ef4444' }}>*</span>
            </label>
            <input
              type="text"
              value={manualInput.completion_no}
              onChange={(e) =>
                handleManualChange("completion_no", e.target.value)
              }
              placeholder="請輸入完工單號"
              style={{ 
                width: "100%",
                padding: '10px 12px',
                background: 'rgba(15, 23, 36, 0.8)',
                border: '1px solid rgba(30, 160, 233, 0.3)',
                borderRadius: 8,
                color: '#ffffff',
                fontSize: 13,
                transition: 'all 0.2s ease',
                boxSizing: 'border-box'
              }}
            />
          </div>
          <div>
            <label style={{
              display: 'block',
              marginBottom: 8,
              fontSize: 13,
              fontWeight: 600,
              color: 'rgba(230, 238, 248, 0.9)',
              letterSpacing: '0.3px'
            }}>完工日期</label>
            <input
              type="text"
              placeholder="YYYY/MM/DD"
              value={manualInput.completion_date}
              onChange={(e) =>
                handleManualChange("completion_date", e.target.value)
              }
              style={{ 
                width: "100%",
                padding: '12px 14px',
                background: 'rgba(15, 23, 36, 0.8)',
                border: '1px solid rgba(30, 160, 233, 0.3)',
                borderRadius: 10,
                color: '#ffffff',
                fontSize: 14,
                transition: 'all 0.2s ease',
                boxSizing: 'border-box'
              }}
            />
          </div>
          <div>
            <label style={{
              display: 'block',
              marginBottom: 8,
              fontSize: 13,
              fontWeight: 600,
              color: 'rgba(230, 238, 248, 0.9)',
              letterSpacing: '0.3px'
            }}>入庫日期</label>
            <input
              type="text"
              placeholder="YYYY/MM/DD"
              value={manualInput.stock_in_date}
              onChange={(e) =>
                handleManualChange("stock_in_date", e.target.value)
              }
              style={{ 
                width: "100%",
                padding: '12px 14px',
                background: 'rgba(15, 23, 36, 0.8)',
                border: '1px solid rgba(30, 160, 233, 0.3)',
                borderRadius: 10,
                color: '#ffffff',
                fontSize: 14,
                transition: 'all 0.2s ease',
                boxSizing: 'border-box'
              }}
            />
          </div>
          <div>
            <label style={{
              display: 'block',
              marginBottom: 8,
              fontSize: 13,
              fontWeight: 600,
              color: 'rgba(230, 238, 248, 0.9)',
              letterSpacing: '0.3px'
            }}>
              完工品號 <span style={{ color: '#ef4444' }}>*</span>
            </label>
            <input
              type="text"
              value={manualInput.finished_item_no}
              onChange={(e) =>
                handleManualChange("finished_item_no", e.target.value)
              }
              placeholder="請輸入完工品號"
              style={{ 
                width: "100%",
                padding: '12px 14px',
                background: 'rgba(15, 23, 36, 0.8)',
                border: '1px solid rgba(30, 160, 233, 0.3)',
                borderRadius: 10,
                color: '#ffffff',
                fontSize: 14,
                transition: 'all 0.2s ease',
                boxSizing: 'border-box'
              }}
            />
          </div>
          <div>
            <label style={{
              display: 'block',
              marginBottom: 8,
              fontSize: 13,
              fontWeight: 600,
              color: 'rgba(230, 238, 248, 0.9)',
              letterSpacing: '0.3px'
            }}>完工數量</label>
            <input
              type="number"
              value={manualInput.completed_qty || ""}
              onChange={(e) =>
                handleManualChange("completed_qty", e.target.value)
              }
              placeholder="0"
              style={{ 
                width: "100%",
                padding: '12px 14px',
                background: 'rgba(15, 23, 36, 0.8)',
                border: '1px solid rgba(30, 160, 233, 0.3)',
                borderRadius: 10,
                color: '#ffffff',
                fontSize: 14,
                transition: 'all 0.2s ease',
                boxSizing: 'border-box'
              }}
            />
          </div>
          <div>
            <label style={{
              display: 'block',
              marginBottom: 8,
              fontSize: 13,
              fontWeight: 600,
              color: 'rgba(230, 238, 248, 0.9)',
              letterSpacing: '0.3px'
            }}>機台代號</label>
            <input
              type="text"
              value={manualInput.machine_code}
              onChange={(e) =>
                handleManualChange("machine_code", e.target.value)
              }
              placeholder="選填"
              style={{ 
                width: "100%",
                padding: '12px 14px',
                background: 'rgba(15, 23, 36, 0.8)',
                border: '1px solid rgba(30, 160, 233, 0.3)',
                borderRadius: 10,
                color: '#ffffff',
                fontSize: 14,
                transition: 'all 0.2s ease',
                boxSizing: 'border-box'
              }}
            />
          </div>
          <div>
            <label style={{
              display: 'block',
              marginBottom: 8,
              fontSize: 13,
              fontWeight: 600,
              color: 'rgba(230, 238, 248, 0.9)',
              letterSpacing: '0.3px'
            }}>模具代號</label>
            <input
              type="text"
              value={manualInput.mold_code}
              onChange={(e) =>
                handleManualChange("mold_code", e.target.value)
              }
              placeholder="選填"
              style={{ 
                width: "100%",
                padding: '12px 14px',
                background: 'rgba(15, 23, 36, 0.8)',
                border: '1px solid rgba(30, 160, 233, 0.3)',
                borderRadius: 10,
                color: '#ffffff',
                fontSize: 14,
                transition: 'all 0.2s ease',
                boxSizing: 'border-box'
              }}
            />
          </div>

          <div style={{ display: 'flex', gap: 10, gridColumn: '1 / -1', justifyContent: 'flex-end', marginTop: 4 }}>
            <button
              type="button"
              onClick={() => setManualInput({
                completion_no: "",
                completion_date: "",
                stock_in_date: "",
                finished_item_no: "",
                completed_qty: 0,
                machine_code: "",
                mold_code: "",
              })}
              style={{
                padding: "10px 20px",
                borderRadius: 8,
                border: '1px solid rgba(148, 163, 184, 0.3)',
                background: 'linear-gradient(135deg, rgba(148, 163, 184, 0.2), rgba(100, 116, 139, 0.15))',
                color: 'rgba(230, 238, 248, 0.9)',
                cursor: "pointer",
                fontSize: 13,
                fontWeight: 600,
                transition: 'all 0.2s ease'
              }}
            >
              清空
            </button>
            <button
              type="submit"
              disabled={!canManualSubmit}
              style={{
                padding: "10px 24px",
                borderRadius: 8,
                border: 'none',
                background: canManualSubmit 
                  ? 'linear-gradient(135deg, #22c55e, #16a34a)' 
                  : 'linear-gradient(135deg, #6b7280, #4b5563)',
                color: "white",
                cursor: canManualSubmit ? "pointer" : "not-allowed",
                fontSize: 13,
                fontWeight: 700,
                transition: 'all 0.3s ease',
                boxShadow: canManualSubmit ? '0 4px 12px rgba(34, 197, 94, 0.3)' : 'none',
                opacity: canManualSubmit ? 1 : 0.6
              }}
            >
              {loading ? "送出中..." : "✓ 新增報完工"}
            </button>
          </div>
        </form>
      </div>

      {/* 🔹 Excel 匯入區 */}
      <div
        style={{
          marginBottom: 24,
          padding: '20px',
          borderRadius: 12,
          background: 'linear-gradient(135deg, rgba(30, 160, 233, 0.15), rgba(124, 58, 237, 0.1))',
          border: '1px solid rgba(30, 160, 233, 0.3)',
          boxShadow: '0 4px 16px rgba(0, 0, 0, 0.2)'
        }}
      >
        <h3 style={{ 
          marginBottom: 16, 
          fontSize: 16,
          fontWeight: 700,
          color: '#1ea0e9',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          letterSpacing: '0.3px'
        }}>
          <span style={{ fontSize: 20 }}>📤</span>
          Excel 批次匯入
        </h3>
        <div
          style={{
            display: "flex",
            gap: 12,
            alignItems: "center",
            flexWrap: "wrap",
          }}
        >
          <label style={{
            padding: '10px 20px',
            borderRadius: 8,
            background: 'linear-gradient(135deg, rgba(255, 255, 255, 0.1), rgba(255, 255, 255, 0.05))',
            border: '2px dashed rgba(30, 160, 233, 0.5)',
            color: '#1ea0e9',
            cursor: 'pointer',
            fontSize: 13,
            fontWeight: 600,
            transition: 'all 0.2s ease',
            display: 'inline-block'
          }}>
            📁 選擇 Excel 檔案
            <input
              type="file"
              accept=".xlsx,.xls"
              onChange={handleFileChange}
              style={{ display: 'none' }}
            />
          </label>
          <span style={{ 
            opacity: 0.9,
            fontSize: 13,
            color: 'rgba(230, 238, 248, 0.8)',
            padding: '6px 12px',
            background: 'rgba(15, 23, 36, 0.6)',
            borderRadius: 6,
            border: '1px solid rgba(30, 160, 233, 0.2)'
          }}>
            {fileName ? `✓ ${fileName}` : "尚未選擇檔案"}
          </span>

          <button
            disabled={!canImport}
            onClick={handleImport}
            style={{
              padding: "10px 24px",
              borderRadius: 8,
              border: 'none',
              background: canImport 
                ? 'linear-gradient(135deg, #1ea0e9, #7c3aed)' 
                : 'linear-gradient(135deg, #6b7280, #4b5563)',
              color: "white",
              cursor: canImport ? "pointer" : "not-allowed",
              fontSize: 13,
              fontWeight: 700,
              transition: 'all 0.3s ease',
              boxShadow: canImport ? '0 4px 12px rgba(30, 160, 233, 0.3)' : 'none',
              opacity: canImport ? 1 : 0.6,
              marginLeft: 'auto'
            }}
          >
            {loading ? "匯入中..." : "⬆️ 匯入資料庫"}
          </button>
        </div>
      </div>

      {error && (
        <div
          style={{
            marginBottom: 24,
            padding: '16px 20px',
            borderRadius: 10,
            background: 'linear-gradient(135deg, rgba(239, 68, 68, 0.2), rgba(220, 38, 38, 0.1))',
            border: '1px solid rgba(239, 68, 68, 0.4)',
            color: "#ef4444",
            whiteSpace: "pre-wrap",
            fontSize: 14,
            lineHeight: 1.6
          }}
        >
          <strong>❌ 錯誤：</strong> {error}
        </div>
      )}

      {batchResult && (
        <div style={{ 
          marginBottom: 24,
          padding: '16px 20px',
          borderRadius: 10,
          background: 'linear-gradient(135deg, rgba(34, 197, 94, 0.2), rgba(22, 163, 74, 0.1))',
          border: '1px solid rgba(34, 197, 94, 0.4)',
          color: "#22c55e",
          fontSize: 14,
          lineHeight: 1.6
        }}>
          <div style={{ fontWeight: 700, marginBottom: 8 }}>
            ✅ 匯入完成
          </div>
          <div style={{ color: 'rgba(230, 238, 248, 0.9)' }}>
            成功新增：<strong style={{ color: '#22c55e' }}>{batchResult.inserted}</strong> 筆　
            跳過：<strong style={{ color: '#eab308' }}>{batchResult.skipped}</strong> 筆
          </div>
          {batchResult.skipped_completion_nos?.length > 0 && (
            <div style={{ 
              marginTop: 10,
              padding: '10px',
              background: 'rgba(234, 179, 8, 0.1)',
              borderRadius: 6,
              color: "#eab308",
              fontSize: 13
            }}>
              ⚠️ 跳過（重複完工單號）：
              <div style={{ marginTop: 4, fontFamily: 'monospace' }}>
                {batchResult.skipped_completion_nos.join(", ")}
              </div>
            </div>
          )}
        </div>
      )}

      <div style={{ marginTop: 24 }}>
        <h3 style={{ 
          marginBottom: 12,
          fontSize: 16,
          fontWeight: 700,
          color: 'rgba(230, 238, 248, 0.9)',
          display: 'flex',
          alignItems: 'center',
          gap: 8
        }}>
          <span style={{ fontSize: 18 }}>👁️</span>
          Excel 預覽
        </h3>
        <SimpleTable rows={previewRows} />
      </div>

      <div style={{ marginTop: 24 }}>
        <h3 style={{ 
          marginBottom: 12,
          fontSize: 16,
          fontWeight: 700,
          color: 'rgba(230, 238, 248, 0.9)',
          display: 'flex',
          alignItems: 'center',
          gap: 8
        }}>
          <span style={{ fontSize: 18 }}>💾</span>
          資料庫現有報完工資料
        </h3>
        <SimpleTable rows={dbRows} />
      </div>
    </div>
  );
}
