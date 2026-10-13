import { useEffect, useState } from "react";
import { X } from "lucide-react";
import {
    correctionStatusLabel,
    listFileCorrections,
    type FileCorrectionListItem,
} from "~/api/fileCorrection";
import s from "../PortalKnowledgeWorkbench.module.css";

interface FileCorrectionHistoryDrawerProps {
    fileId: string;
    onClose: () => void;
}

/** 右侧边栏里的纠错历史, 和属性面板同一层抽屉. */
export function FileCorrectionHistoryDrawer({
    fileId,
    onClose,
}: FileCorrectionHistoryDrawerProps) {
    const [items, setItems] = useState<FileCorrectionListItem[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");

    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        setError("");
        void listFileCorrections(fileId)
            .then((rows) => {
                if (!cancelled) setItems(rows);
            })
            .catch((loadError) => {
                if (!cancelled) setError(loadError instanceof Error ? loadError.message : "读取纠错记录失败");
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [fileId]);

    return (
        <aside className={s.drawer} data-testid="file-correction-history-drawer">
            <div className={s.drawerHeader}>
                <div className={s.drawerTitle}>纠错历史</div>
                <button type="button" className={s.toolbarButton} onClick={onClose} aria-label="关闭">
                    <X size={14} />
                </button>
            </div>
            <div className={s.drawerBody}>
                {loading ? <div className={s.detailValue}>正在加载...</div> : null}
                {error ? <div className={s.detailValue}>{error}</div> : null}
                {!loading && !error && items.length === 0 ? <div className={s.detailValue}>还没有纠错反馈</div> : null}
                <div className={s.detailList}>
                    {items.map((item) => (
                        <div key={item.correction_id} className={s.correctionHistoryCard}>
                            <div className={s.detailItem}>
                                <span className={s.detailLabel}>反馈人</span>
                                <span className={s.detailValue}>{item.applicant_user_name || "-"}</span>
                            </div>
                            <div className={s.detailItem}>
                                <span className={s.detailLabel}>当时文件</span>
                                <span className={s.detailValue}>{item.file_name || "-"}</span>
                            </div>
                            <div className={s.detailItem}>
                                <span className={s.detailLabel}>纠错内容</span>
                                <span className={`${s.detailValue} ${s.detailValueWrap}`}>{item.content || "-"}</span>
                            </div>
                            <div className={s.detailItem}>
                                <span className={s.detailLabel}>状态</span>
                                <span className={s.detailValue}>{correctionStatusLabel(item.status, item.award_kind)}</span>
                            </div>
                            {item.create_time ? (
                                <div className={s.detailItem}>
                                    <span className={s.detailLabel}>时间</span>
                                    <span className={s.detailValue}>{item.create_time}</span>
                                </div>
                            ) : null}
                        </div>
                    ))}
                </div>
            </div>
        </aside>
    );
}
