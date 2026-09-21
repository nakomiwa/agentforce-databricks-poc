import { LightningElement, api } from 'lwc';

/**
 * Databricks が返す描画スペック JSON（if_render_spec v1）を描くだけの汎用レンダラ。
 *
 * 設計の要点は 2 つ。
 *  1. 整形しない。値は Databricks 側で表示可能な文字列になっている前提で、そのまま出す
 *  2. 知らない type のブロックは黙って飛ばす。Databricks が先に新部品を送っても壊れない
 *
 * テンプレート側で分岐を書けないので、JS で種別フラグと CSS クラスまで作って渡す。
 */

const TONE_TEXT = {
    muted: 'slds-text-color_weak',
    success: 'slds-text-color_success',
    warning: 'slds-text-color_warning',
    error: 'slds-text-color_error'
};

const TONE_BADGE = {
    success: 'slds-badge slds-theme_success',
    warning: 'slds-badge slds-theme_warning',
    error: 'slds-badge slds-theme_error'
};

export default class DatabricksBlockRenderer extends LightningElement {
    title = '';
    subtitle = '';
    blocks = [];
    parseError = '';

    _value;

    @api
    get value() {
        return this._value;
    }
    set value(v) {
        this._value = v;
        this.build(v);
    }

    get hasBlocks() {
        return this.blocks.length > 0;
    }

    build(raw) {
        this.title = '';
        this.subtitle = '';
        this.blocks = [];
        this.parseError = '';

        const payload = this.asObject(raw);
        if (!payload) {
            this.parseError = 'データを受け取れませんでした。';
            return;
        }

        this.title = payload.title || 'Databricks';

        const spec = this.asObject(payload.specJson) || payload;
        if (!spec || !Array.isArray(spec.blocks)) {
            this.parseError = '描画スペックを解釈できませんでした。';
            return;
        }

        this.subtitle = spec.subtitle || '';
        if (spec.title) {
            this.title = spec.title;
        }

        this.blocks = spec.blocks
            .map((b, i) => this.toBlock(b, i))
            .filter((b) => b !== null);
    }

    asObject(v) {
        if (!v) {
            return null;
        }
        if (typeof v === 'object') {
            return v;
        }
        if (typeof v === 'string') {
            try {
                return JSON.parse(v);
            } catch (e) {
                return null;
            }
        }
        return null;
    }

    toBlock(b, index) {
        if (!b || typeof b !== 'object') {
            return null;
        }
        const base = {
            key: `b${index}`,
            blockTitle: b.title || '',
            isText: false,
            isKpi: false,
            isList: false,
            isTable: false,
            isBadge: false,
            isHtml: false,
            isImage: false
        };

        switch (b.type) {
            case 'text':
                return {
                    ...base,
                    isText: true,
                    text: b.value || '',
                    textClass: this.textClass(b.tone)
                };

            case 'kpiGrid': {
                const size = b.columns === 1 ? 12 : 6;
                return {
                    ...base,
                    isKpi: true,
                    items: (b.items || []).map((it, i) => ({
                        key: `k${i}`,
                        label: it.label || '',
                        value: it.value || '',
                        valueClass: `kpi-value ${this.textClass(it.tone)}`,
                        colClass: `slds-col slds-size_${size}-of-12 slds-var-p-around_xx-small`
                    }))
                };
            }

            case 'list':
                return {
                    ...base,
                    isList: true,
                    items: (b.items || []).map((it, i) => ({
                        key: `l${i}`,
                        primary: it.primary || '',
                        secondary: it.secondary || '',
                        value: it.value || '',
                        badgeLabel: it.badge ? it.badge.label : '',
                        badgeClass: it.badge ? this.badgeClass(it.badge.tone) : '',
                        hasBadge: !!(it.badge && it.badge.label)
                    }))
                };

            case 'table': {
                const columns = b.columns || [];
                return {
                    ...base,
                    isTable: true,
                    headers: columns.map((c, i) => ({
                        key: `h${i}`,
                        label: c.label || '',
                        headClass: this.alignClass(c.align)
                    })),
                    rows: (b.rows || []).map((r, i) => ({
                        key: `r${i}`,
                        rowClass: this.textClass(r._tone),
                        cells: columns.map((c, j) => ({
                            key: `c${j}`,
                            text: r[c.key] === undefined || r[c.key] === null ? '-' : r[c.key],
                            cellClass: this.alignClass(c.align)
                        }))
                    }))
                };
            }

            case 'badge':
                return {
                    ...base,
                    isBadge: true,
                    badgeLabel: b.label || '',
                    badgeClass: this.badgeClass(b.tone)
                };

            case 'html':
                return { ...base, isHtml: true, html: b.value || '' };

            case 'image':
                return {
                    ...base,
                    isImage: true,
                    src: b.src || '',
                    alt: b.alt || '',
                    imgStyle: b.maxHeight ? `max-height:${b.maxHeight}px;max-width:100%` : 'max-width:100%'
                };

            default:
                // 知らない type は読み飛ばす（前方互換）
                return null;
        }
    }

    textClass(tone) {
        return TONE_TEXT[tone] || '';
    }

    badgeClass(tone) {
        return TONE_BADGE[tone] || 'slds-badge';
    }

    alignClass(align) {
        if (align === 'right') {
            return 'align-right';
        }
        if (align === 'center') {
            return 'align-center';
        }
        return '';
    }
}
