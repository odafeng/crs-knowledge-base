// Clinical treatment pathway schematic on mCRC topic pages: renders verified lines and Taiwan TFDA/NHI status
// straight from the topic's standardOfCare and regulatory data.
import { Status } from "@/components/reading";
import type { TreatmentPathwayModel } from "@/lib/pathway";

function Arrow({ label }: { label?: string }) {
  return (
    <div className="pathway__connector" aria-hidden="true">
      {label && <span className="pathway__connector-label">{label}</span>}
      <svg
        className="pathway__arrow"
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

export function TreatmentPathway({ model }: { model: TreatmentPathwayModel }) {
  return (
    <section className="page__section" aria-labelledby="pathway">
      <h2 id="pathway">治療路徑與給付節點</h2>
      <div className={`pathway pathway--${model.flow}`}>
        <div className="pathway__root">
          <span className="pathway__root-kicker">分子分型</span>
          <strong className="pathway__root-name">{model.topicLabel}</strong>
          <span className="pathway__root-sub">
            {model.flow === "branched"
              ? "依分期分流"
              : model.flow === "sequential"
                ? "依線別銜接"
                : "核心標靶節點"}
          </span>
        </div>

        <Arrow />

        <ol className="pathway__stages">
          {model.stages.map((stage, index) => (
            <li className="pathway__stage-item" key={stage.id}>
              {index > 0 && model.flow === "sequential" && (
                <Arrow label="惡化／後線" />
              )}
              <div className="pathway__stage">
                <div className="pathway__stage-head">
                  <span className="pathway__badge">{stage.badge}</span>
                  <a className="pathway__jump" href={`#${stage.id}`}>
                    看治療說明
                  </a>
                </div>
                <h3 className="pathway__stage-title">{stage.title}</h3>
                <ul className="pathway__regimens">
                  {stage.regimens.map((row) => (
                    <li className="pathway__regimen" key={row.regimen}>
                      <p className="pathway__regimen-name">{row.regimen}</p>
                      <div className="pathway__statuses">
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
                          <span className="pathway__clause">
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
      <p className="pathway__note">
        路徑與核准／給付狀態取自下方已查核的
        <a href="#reg">核准與給付現況</a>與<a href="#soc">治療現況</a>
        ，臨床決策請依病人個別狀況與現行指引判斷。
      </p>
    </section>
  );
}
