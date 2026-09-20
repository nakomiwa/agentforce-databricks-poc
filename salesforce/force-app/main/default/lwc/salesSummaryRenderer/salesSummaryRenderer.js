import { LightningElement, api } from 'lwc';

export default class SalesSummaryRenderer extends LightningElement {
    title = '営業サマリ';
    scopeText = '';
    summaryText = '-';

    totalAmountText = '-';
    dealCountText = '-';
    wonCountText = '-';
    winRateText = '-';

    rows = [];
    footNote = 'データを受け取れませんでした。';

    _value;

    @api
    get value() {
        return this._value;
    }
    set value(v) {
        this._value = v;
        this.build(v);
    }

    build(raw) {
        let data = raw;
        if (typeof data === 'string') {
            try {
                data = JSON.parse(data);
            } catch (e) {
                data = null;
            }
        }
        if (!data) {
            return;
        }

        this.title = data.title ? data.title : '営業サマリ';
        this.summaryText = data.summaryText ? data.summaryText : '-';

        // KPI と明細は rowsJson に同梱されている
        let payload = {};
        if (data.rowsJson) {
            try {
                payload = JSON.parse(data.rowsJson);
            } catch (e) {
                payload = {};
            }
        }

        const kpi = payload.kpi || {};
        this.totalAmountText = kpi.totalAmountText || '-';
        this.dealCountText = kpi.dealCountText || '-';
        this.wonCountText = kpi.wonCountText || '-';
        this.winRateText = kpi.winRateText || '-';
        this.scopeText =
            kpi.region && kpi.period ? kpi.region + ' ／ ' + kpi.period : '';

        const src = payload.rows || [];
        const out = [];
        for (let i = 0; i < src.length; i++) {
            const r = src[i];
            out.push({
                key: 'row-' + i,
                rank: i + 1,
                opportunityName: r.opportunityName,
                accountName: r.accountName,
                ownerName: r.ownerName,
                amountText: r.amountText,
                stage: r.stage,
                closeDate: r.closeDate,
                stageClass: this.stageClass(r.stage)
            });
        }

        this.rows = out;
        this.footNote =
            out.length > 0
                ? '金額上位 ' + out.length + ' 件を表示しています。'
                : '該当する案件がありませんでした。';
    }

    stageClass(stage) {
        const base = 'slds-badge slds-var-m-right_xx-small ';
        switch (stage) {
            case '受注':
                return base + 'slds-theme_success';
            case '失注':
                return base + 'slds-theme_error';
            case '最終交渉':
                return base + 'slds-theme_warning';
            default:
                return base;
        }
    }
}
