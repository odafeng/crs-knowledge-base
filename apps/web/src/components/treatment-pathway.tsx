// Clinical treatment pathway schematic on mCRC topic pages: renders verified lines and Taiwan TFDA/NHI status
// straight from the topic's standardOfCare and regulatory data.
import { Status } from "@/components/reading";
import type { TreatmentPathwayModel } from "@/lib/pathway";
import styles from "./treatment-pathway.module.css";

function Arrow({ label }: { label?: string }) {
  return (
    <div className={styles.connector} aria-hidden="true">
      {label && <span className={styles.connectorLabel}>{label}</span>}
      <svg
        className={styles.arrow}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M5 12h14M13 6l6 6-6 6" />
      </svg>
    </div>
  );
}

const FLOW_CLASS: Record<TreatmentPathwayModel["flow"], string> = {
  sequential: styles.sequential,
  branched: styles.branched,
  single: styles.single,
};

export function TreatmentPathway({ model }: { model: TreatmentPathwayModel }) {
  return (
    <section className="page__section" aria-labelledby="pathway">
      <h2 id="pathway">治療路徑與給付節點</h2>
      <div className={`${styles.pathway} ${FLOW_CLASS[model.flow]}`}>
        <div className={styles.root}>
          <span className={styles.rootKicker}>分子分型</span>
          <strong className={styles.rootName}>{model.topicLabel}</strong>
          <span className={styles.rootSub}>
            {model.flow === "branched"
              ? "依分期分流"
              : model.flow === "sequential"
                ? "依線別銜接"
                : "核心標靶節點"}
          </span>
        </div>

        <Arrow />

        <ol className={styles.stages}>
          {model.stages.map((stage, index) => (
            <li className={styles.stageItem} key={stage.id}>
              {index > 0 && model.flow === "sequential" && (
                <Arrow label="惡化／後線" />
              )}
              <div className={styles.stage}>
                <div className={styles.stageHead}>
                  <span className={styles.badge}>{stage.badge}</span>
                  <a className={styles.jump} href={`#${stage.id}`}>
                    看治療說明
                  </a>
                </div>
                <h3 className={styles.stageTitle}>{stage.title}</h3>
                <ul className={styles.regimens}>
                  {stage.regimens.map((row) => (
                    <li className={styles.regimen} key={row.regimen}>
                      <p className={styles.regimenName}>{row.regimen}</p>
                      <div className={styles.statuses}>
                        {row.tfda === "none" && row.fda !== "none" && (
                          <Status
                            regulator="fda"
                            value={row.fda}
                            prefix="FDA "
                          />
                        )}
                        <Status
                          regulator="tfda"
                          value={row.tfda}
                          prefix="TFDA "
                        />
                        <Status
                          regulator="nhi"
                          value={row.nhi}
                          prefix="健保 "
                        />
                        {row.nhiClause && (
                          <span className={styles.clause}>
                            給付規定 {row.nhiClause}
                          </span>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            </li>
          ))}
        </ol>
      </div>
      <p className={styles.note}>
        路徑與核准／給付狀態取自下方已查核的
        <a href="#reg">核准與給付現況</a>與<a href="#soc">治療現況</a>
        ，臨床決策請依病人個別狀況與現行指引判斷。
      </p>
    </section>
  );
}
