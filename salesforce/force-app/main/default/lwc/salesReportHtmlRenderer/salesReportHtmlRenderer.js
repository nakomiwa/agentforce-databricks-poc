import { LightningElement, api } from 'lwc';

export default class SalesReportHtmlRenderer extends LightningElement {
    title = '営業レポート';
    html = '';
    generatedAt = '';

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
            this.html = '<p>データを受け取れませんでした。</p>';
            return;
        }

        this.title = data.title ? data.title : '営業レポート';
        // Databricks が返す HTML フラグメント。
        // lightning-formatted-rich-text が許可タグのみ描画し、それ以外は除去する。
        this.html = data.html ? data.html : '<p>レポートが空でした。</p>';
        this.generatedAt = data.generatedAt ? data.generatedAt : '';
    }
}
