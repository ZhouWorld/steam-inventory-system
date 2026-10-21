// ============================================================
// Steam 库存管理 API - Cloudflare Worker
// ============================================================

const CORS_HEADERS = {
	'Access-Control-Allow-Origin': '*',
	'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
	'Access-Control-Allow-Headers': 'Content-Type, X-Api-Key',
	'Access-Control-Max-Age': '86400',
};

function json(data, status = 200) {
	return new Response(JSON.stringify(data), {
		status,
		headers: {
			'Content-Type': 'application/json; charset=utf-8',
			...CORS_HEADERS,
		},
	});
}

export default {
	async fetch(request, env) {
		const url = new URL(request.url);
		const path = url.pathname;

		// ⭐ CORS 预检
		if (request.method === 'OPTIONS') {
			return new Response(null, { status: 204, headers: CORS_HEADERS });
		}

		try {
			// ---------- 健康检查 ----------
			if (path === '/' || path === '/api/health') {
				return json({ ok: true, service: 'steam-inventory-api', time: new Date().toISOString() });
			}

			// ---------- GET /api/inventory ----------
			// 参数：page（默认1）、pageSize（默认50，最大200）、sortBy（float|name|assetid）
			if (path === '/api/inventory' && request.method === 'GET') {
				const page = Math.max(1, parseInt(url.searchParams.get('page') || '1', 10));
				const pageSize = Math.min(200, Math.max(1, parseInt(url.searchParams.get('pageSize') || '50', 10)));
				const sortBy = url.searchParams.get('sortBy') || 'assetid';
				const offset = (page - 1) * pageSize;

				const sortMap = {
					float: 'a.float_value',
					name: 'd.market_hash_name',
					assetid: 'a.assetid',
				};
				const orderBy = sortMap[sortBy] || 'a.assetid';

				const countRow = await env.DB.prepare('SELECT COUNT(*) AS total FROM assets').first();
				const total = countRow ? countRow.total : 0;

				const { results } = await env.DB.prepare(
					`SELECT a.assetid, a.amount, a.float_value, a.paint_seed, a.paint_index,
                  a.def_index, a.quality, a.tradable, a.marketable, a.float_source,
                  a.first_seen_at, a.last_seen_at,
                  d.market_hash_name, d.name, d.icon_url, d.commodity
           FROM assets a
           LEFT JOIN item_descriptions d ON a.description_id = d.id
           ORDER BY ${orderBy}
           LIMIT ? OFFSET ?`,
				)
					.bind(pageSize, offset)
					.all();

				return json({
					page,
					pageSize,
					total,
					totalPages: Math.ceil(total / pageSize),
					items: results || [],
				});
			}

			// ---------- GET /api/float?assetid=xxx ----------
			if (path === '/api/float' && request.method === 'GET') {
				const aid = (url.searchParams.get('assetid') || '').trim();
				if (!aid) return json({ error: 'missing assetid' }, 400);

				const row = await env.DB.prepare(
					`SELECT a.assetid, a.float_value, a.float_source,
                  d.market_hash_name
           FROM assets a
           LEFT JOIN item_descriptions d ON a.description_id = d.id
           WHERE a.assetid = ?`,
				)
					.bind(aid)
					.first();

				if (!row) return json({ assetid: aid, float: null, exists: false });
				return json({
					assetid: row.assetid,
					float: row.float_value,
					floatSource: row.float_source,
					marketHashName: row.market_hash_name,
					exists: true,
				});
			}

			// ---------- POST /api/floats ----------
			// body: { assetids: ["...", "..."] }
			// D1 免费版单次绑定参数上限 100，这里按 100 一批拆
			if (path === '/api/floats' && request.method === 'POST') {
				const body = await request.json().catch(() => ({}));
				const raw = Array.isArray(body.assetids) ? body.assetids : [];
				const aids = raw.map(String).filter(Boolean);
				if (aids.length === 0) return json({ floats: {}, requested: 0, found: 0 });

				const BATCH = 100;
				const out = {};

				for (let i = 0; i < aids.length; i += BATCH) {
					const batch = aids.slice(i, i + BATCH);
					const placeholders = batch.map(() => '?').join(',');
					const { results } = await env.DB.prepare(
						`SELECT assetid, float_value, float_source FROM assets WHERE assetid IN (${placeholders})`,
					)
						.bind(...batch)
						.all();

					for (const r of results || []) {
						out[r.assetid] = { float: r.float_value, source: r.float_source };
					}
				}

				return json({ floats: out, requested: aids.length, found: Object.keys(out).length });
			}

			// ---------- GET /api/stats ----------
			if (path === '/api/stats' && request.method === 'GET') {
				const totalRow = await env.DB.prepare('SELECT COUNT(*) AS total FROM assets').first();
				const withFloatRow = await env.DB.prepare('SELECT COUNT(*) AS withFloat FROM assets WHERE float_value IS NOT NULL').first();
				const bySource = await env.DB.prepare('SELECT float_source, COUNT(*) AS cnt FROM assets GROUP BY float_source').all();

				return json({
					total: totalRow ? totalRow.total : 0,
					withFloat: withFloatRow ? withFloatRow.withFloat : 0,
					bySource: bySource.results || [],
				});
			}

			return json({ error: 'not found', path }, 404);
		} catch (e) {
			console.error('[worker] error:', e);
			return json({ error: String(e && e.message ? e.message : e) }, 500);
		}
	},
};
