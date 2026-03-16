/* ─────────────────────────────────────────────────────────────
   Company Intelligence — Frontend Logic
   ───────────────────────────────────────────────────────────── */

// ── Field → Card Category Mapping ────────────────────────────

const CARD_CATEGORIES = [
    {
        id: "overview",
        icon: "🏢",
        title: "Company Overview",
        fields: [
            "name", "short_name", "category", "industry", "nature_of_company",
            "incorporation_year", "headquarters_address", "operating_countries",
            "office_count", "office_locations", "overview_text",
            "vision_statement", "mission_statement", "core_values",
            "history_timeline", "recent_news"
        ]
    },
    {
        id: "online",
        icon: "🌐",
        title: "Online Presence",
        fields: [
            "website_url", "linkedin_url", "twitter_handle", "facebook_url",
            "instagram_url", "primary_contact_email", "primary_phone_number",
            "marketing_video_url", "website_quality", "website_rating",
            "website_traffic_rank", "social_media_followers",
            "brand_sentiment_score", "customer_testimonials", "logo_url"
        ]
    },
    {
        id: "market",
        icon: "📊",
        title: "Products & Market",
        fields: [
            "offerings_description", "focus_sectors", "pain_points_addressed",
            "top_customers", "core_value_proposition", "unique_differentiators",
            "competitive_advantages", "weaknesses_gaps", "key_challenges_needs",
            "key_competitors", "market_share_percentage", "sales_motion",
            "benchmark_vs_peers", "case_studies", "go_to_market_strategy",
            "tam", "sam", "som"
        ]
    },
    {
        id: "strategy",
        icon: "🚀",
        title: "Strategy & Innovation",
        fields: [
            "strategic_priorities", "future_projections", "innovation_roadmap",
            "product_pipeline", "awards_recognitions", "event_participation",
            "industry_associations"
        ]
    },
    {
        id: "financials",
        icon: "💰",
        title: "Financials",
        fields: [
            "annual_revenue", "annual_profit", "revenue_mix", "valuation",
            "yoy_growth_rate", "profitability_status", "key_investors",
            "recent_funding_rounds", "total_capital_raised",
            "customer_acquisition_cost", "customer_lifetime_value",
            "cac_ltv_ratio", "churn_rate", "net_promoter_score",
            "burn_rate", "runway_months", "burn_multiplier",
            "brand_value", "r_and_d_investment"
        ]
    },
    {
        id: "culture",
        icon: "👥",
        title: "People & Culture",
        fields: [
            "employee_size", "glassdoor_rating", "indeed_rating", "google_rating",
            "work_culture_summary", "diversity_metrics", "diversity_inclusion_score",
            "manager_quality", "psychological_safety", "feedback_culture",
            "ethical_standards", "burnout_risk", "layoff_history",
            "mission_clarity", "sustainability_csr", "crisis_behavior",
            "hiring_velocity", "employee_turnover", "avg_retention_tenure"
        ]
    },
    {
        id: "benefits",
        icon: "🎁",
        title: "Benefits & Compensation",
        fields: [
            "leave_policy", "health_support", "fixed_vs_variable_pay",
            "bonus_predictability", "esops_incentives", "family_health_insurance",
            "relocation_support", "lifestyle_benefits"
        ]
    },
    {
        id: "workplace",
        icon: "🏠",
        title: "Workplace",
        fields: [
            "remote_policy_details", "typical_hours", "overtime_expectations",
            "weekend_work", "flexibility_level", "location_centrality",
            "public_transport_access", "cab_policy", "airport_commute_time",
            "office_zone_type", "area_safety", "safety_policies",
            "infrastructure_safety", "emergency_preparedness"
        ]
    },
    {
        id: "growth",
        icon: "📈",
        title: "Growth & Career",
        fields: [
            "training_spend", "onboarding_quality", "learning_culture",
            "exposure_quality", "mentorship_availability", "internal_mobility",
            "promotion_clarity", "tools_access", "role_clarity",
            "early_ownership", "work_impact", "execution_thinking_balance",
            "automation_level", "cross_functional_exposure", "exit_opportunities",
            "skill_relevance", "external_recognition", "network_strength",
            "global_exposure"
        ]
    },
    {
        id: "leadership",
        icon: "👤",
        title: "Leadership & Contacts",
        fields: [
            "ceo_name", "ceo_linkedin_url", "key_leaders", "board_members",
            "warm_intro_pathways", "decision_maker_access",
            "contact_person_name", "contact_person_title",
            "contact_person_email", "contact_person_phone",
            "company_maturity", "client_quality"
        ]
    },
    {
        id: "risk",
        icon: "⚠️",
        title: "Risk & Compliance",
        fields: [
            "regulatory_status", "legal_issues", "esg_ratings",
            "supply_chain_dependencies", "geopolitical_risks", "macro_risks",
            "carbon_footprint", "ethical_sourcing",
            "customer_concentration_risk", "exit_strategy_history",
            "cybersecurity_posture"
        ]
    },
    {
        id: "tech",
        icon: "💻",
        title: "Technology",
        fields: [
            "tech_stack", "ai_ml_adoption_level", "tech_adoption_rating",
            "technology_partners", "intellectual_property", "partnership_ecosystem"
        ]
    }
];


// ── State ────────────────────────────────────────────────────

let currentJobId = null;
let eventSource = null;


// ── DOM ──────────────────────────────────────────────────────

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function showView(id) {
    $$(".view").forEach(v => v.classList.remove("active"));
    $(`#view-${id}`).classList.add("active");
}


// ── Search ───────────────────────────────────────────────────

$("#search-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const company = $("#company-input").value.trim();
    if (!company) return;

    $("#btn-analyze").disabled = true;

    try {
        const res = await fetch("/api/analyze", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ company_name: company })
        });
        const data = await res.json();
        currentJobId = data.job_id;

        startProgressView(company);
    } catch (err) {
        alert("Failed to start analysis. Please try again.");
        $("#btn-analyze").disabled = false;
    }
});


// ── Progress ─────────────────────────────────────────────────

const STAGE_MAP = {
    "Extract": "stage-extract",
    "Consolidate": "stage-consolidate",
    "Upgrade": "stage-validate",
    "Validate": "stage-validate",
    "Retry": "stage-validate",
    "End": "stage-done",
    "Done": "stage-done",
};

function startProgressView(company) {
    showView("progress");
    $("#progress-company").textContent = company;

    // Reset stages
    $$(".stage").forEach(s => { s.classList.remove("active", "completed"); });
    $$(".stage-connector").forEach(c => { c.classList.remove("completed"); });
    $("#log-content").innerHTML = "";
    $("#log-badge").textContent = "Streaming";

    // Mark first stage active
    $("#stage-research").classList.add("active");

    // Start SSE
    connectSSE();
}

function connectSSE() {
    if (eventSource) eventSource.close();

    eventSource = new EventSource(`/api/status/${currentJobId}`);

    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);

        // Add log line
        const logEl = document.createElement("div");
        logEl.className = "log-line" + (data.message.includes("Node:") ? " highlight" : "");
        logEl.textContent = data.message;
        $("#log-content").appendChild(logEl);
        $("#log-content").scrollTop = $("#log-content").scrollHeight;

        // Update stage indicators
        if (data.stage) {
            updateStages(data.stage);
        }

        // Handle completion
        if (data.type === "complete") {
            eventSource.close();
            $("#log-badge").textContent = "Complete ✓";
            $("#log-badge").style.background = "#34d399";

            // Mark all stages complete
            $$(".stage").forEach(s => {
                s.classList.remove("active");
                s.classList.add("completed");
            });
            $$(".stage-connector").forEach(c => c.classList.add("completed"));

            // Load results after a short delay
            setTimeout(() => loadResults(), 1500);
        }

        if (data.type === "error") {
            eventSource.close();
            $("#log-badge").textContent = "Error ✗";
            $("#log-badge").style.background = "#f87171";
        }
    };

    eventSource.onerror = () => {
        // SSE connection dropped — check if job is actually done
        setTimeout(async () => {
            try {
                const res = await fetch(`/api/result/${currentJobId}`);
                if (res.ok) {
                    loadResults();
                }
            } catch (e) { }
        }, 2000);
    };
}

function updateStages(currentStage) {
    const stageOrder = ["Research", "Extract", "Consolidate", "Validate", "Done"];
    const stageIds = ["stage-research", "stage-extract", "stage-consolidate", "stage-validate", "stage-done"];
    const connectors = document.querySelectorAll(".stage-connector");

    // Normalize
    let mappedStage = currentStage;
    if (["Upgrade", "Validate", "Retry"].includes(currentStage)) mappedStage = "Validate";
    if (currentStage === "End") mappedStage = "Done";

    const idx = stageOrder.indexOf(mappedStage);
    if (idx < 0) return;

    // Mark previous as completed, current as active
    stageIds.forEach((id, i) => {
        const el = $(`#${id}`);
        el.classList.remove("active", "completed");
        if (i < idx) el.classList.add("completed");
        if (i === idx) el.classList.add("active");
    });

    // Update connectors
    connectors.forEach((c, i) => {
        c.classList.toggle("completed", i < idx);
    });
}


// ── Results ──────────────────────────────────────────────────

async function loadResults() {
    try {
        const res = await fetch(`/api/result/${currentJobId}`);
        if (!res.ok) return;
        const result = await res.json();

        renderResults(result);
        showView("results");
    } catch (err) {
        console.error("Failed to load results:", err);
    }
}

function renderResults(result) {
    const company = result.company || "Unknown";
    const stage3 = result.stage3 || {};
    const data = stage3.data || {};
    const report = stage3.validation_report || {};
    const consolidated = result.consolidated || {};

    // Header
    $("#results-company").textContent = `📋 ${company} — Intelligence Report`;

    const totalFields = Object.keys(data).length;
    const populated = Object.values(data).filter(v => v && v.display_value != null).length;
    const avgConf = totalFields > 0
        ? (Object.values(data).reduce((s, v) => s + (v?.confidence || 0), 0) / totalFields).toFixed(2)
        : "N/A";
    const status = report.status || "unknown";

    $("#results-meta").textContent = `${populated}/${totalFields} fields populated · Avg confidence: ${avgConf} · Status: ${status.toUpperCase()} · ${stage3.retry_count || 0} retries`;

    // Summary cards
    const summaryEl = $("#results-summary");
    summaryEl.innerHTML = `
        <div class="summary-card"><div class="summary-value">${populated}</div><div class="summary-label">Fields Populated</div></div>
        <div class="summary-card"><div class="summary-value">${totalFields}</div><div class="summary-label">Total Fields</div></div>
        <div class="summary-card"><div class="summary-value">${avgConf}</div><div class="summary-label">Avg Confidence</div></div>
        <div class="summary-card"><div class="summary-value" style="${status === 'pass' ? 'color:#34d399;-webkit-text-fill-color:#34d399' : 'color:#f87171;-webkit-text-fill-color:#f87171'}">${status.toUpperCase()}</div><div class="summary-label">Validation</div></div>
        <div class="summary-card"><div class="summary-value">${stage3.retry_count || 0}</div><div class="summary-label">Retry Cycles</div></div>
    `;

    // Build cards
    const grid = $("#cards-grid");
    grid.innerHTML = "";

    CARD_CATEGORIES.forEach(cat => {
        // Filter fields that exist in data
        const catFields = cat.fields.filter(f => f in data || f in consolidated);
        if (catFields.length === 0) return;

        const populatedCount = catFields.filter(f => data[f]?.display_value != null).length;

        const card = document.createElement("div");
        card.className = "data-card";
        card.innerHTML = `
            <div class="card-header">
                <span class="card-icon">${cat.icon}</span>
                <span class="card-title">${cat.title}</span>
                <span class="card-count">${populatedCount}/${catFields.length}</span>
                <span class="card-toggle">▼</span>
            </div>
            <div class="card-body">
                ${catFields.map(f => renderField(f, data[f], consolidated[f])).join("")}
            </div>
        `;

        // Toggle expand/collapse
        card.querySelector(".card-header").addEventListener("click", () => {
            card.classList.toggle("expanded");
        });

        grid.appendChild(card);
    });

    // Expand first card by default
    const firstCard = grid.querySelector(".data-card");
    if (firstCard) firstCard.classList.add("expanded");
}

function renderField(fieldName, fieldData, consolidatedData) {
    const label = fieldName.replace(/_/g, " ");

    let value = "—";
    let conf = 0;
    let source = "";

    if (fieldData) {
        value = fieldData.display_value ?? fieldData.normalized_value ?? "—";
        conf = fieldData.confidence || 0;
        source = fieldData.source || "";
    }

    // If no stage3 data, try consolidated
    if (value === "—" && consolidatedData) {
        value = consolidatedData.value ?? "—";
        source = consolidatedData.source || "";
    }

    // Format long values
    const isNull = value === "—" || value === null || value === undefined;
    let displayValue = isNull ? "Not available" : String(value);

    // Truncate very long strings for display
    if (displayValue.length > 300) {
        displayValue = displayValue.substring(0, 300) + "…";
    }

    // Confidence badge
    let confClass = "confidence-low";
    let confLabel = `${(conf * 100).toFixed(0)}%`;
    if (conf >= 0.8) confClass = "confidence-high";
    else if (conf >= 0.5) confClass = "confidence-medium";

    return `
        <div class="field-row">
            <span class="field-label">${label}</span>
            <span class="field-value${isNull ? ' null' : ''}">${escapeHtml(displayValue)}</span>
            <div class="field-badges">
                ${!isNull ? `<span class="confidence-badge ${confClass}">${confLabel}</span>` : ""}
                ${source ? `<span class="source-badge">${source}</span>` : ""}
            </div>
        </div>
    `;
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}


// ── Download ─────────────────────────────────────────────────

$("#btn-download").addEventListener("click", () => {
    if (!currentJobId) return;
    window.open(`/api/download/${currentJobId}`, "_blank");
});


// ── New Search ───────────────────────────────────────────────

$("#btn-new-search").addEventListener("click", () => {
    showView("search");
    $("#company-input").value = "";
    $("#btn-analyze").disabled = false;
    $("#company-input").focus();
});

// Logo click → home
$(".logo").addEventListener("click", () => {
    showView("search");
    $("#btn-analyze").disabled = false;
});


// ── History ──────────────────────────────────────────────────

$("#btn-history").addEventListener("click", async () => {
    showView("history");
    await loadHistory();
});

$("#btn-back-home").addEventListener("click", () => {
    showView("search");
});

async function loadHistory() {
    const list = $("#history-list");
    list.innerHTML = '<div class="history-empty">Loading...</div>';

    try {
        const res = await fetch("/api/history");
        const items = await res.json();

        if (items.length === 0) {
            list.innerHTML = '<div class="history-empty">No analyses yet. Run your first one!</div>';
            return;
        }

        list.innerHTML = items.map(item => `
            <div class="history-item" data-path="${escapeHtml(item.path)}">
                <span class="history-company">🏢 ${escapeHtml(item.company)}</span>
                <span class="history-time">${new Date(item.timestamp).toLocaleString()}</span>
            </div>
        `).join("");

        // Click to view
        list.querySelectorAll(".history-item").forEach(el => {
            el.addEventListener("click", async () => {
                const path = el.dataset.path;
                try {
                    // For history items, we read the file directly via a small proxy
                    const res = await fetch("/api/history");
                    const items = await res.json();
                    const item = items.find(i => i.path === path);
                    if (item) {
                        const fileRes = await fetch(`/api/result-file?path=${encodeURIComponent(path)}`);
                        if (fileRes.ok) {
                            const result = await fileRes.json();
                            renderResults(result);
                            showView("results");
                        }
                    }
                } catch (e) {
                    console.error("Failed to load history item:", e);
                }
            });
        });
    } catch (err) {
        list.innerHTML = '<div class="history-empty">Failed to load history.</div>';
    }
}
