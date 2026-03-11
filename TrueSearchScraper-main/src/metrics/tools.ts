import http from 'node:http';

import { Pushgateway, Registry, PrometheusContentType } from 'prom-client';

import logger from '../logging.js';
import { PROMETHEUS_GW_URL, ENABLE_METRICS } from '../config.js';


function getPrometheusGw(gwUrl:string, register:Registry): Pushgateway<PrometheusContentType> {
	const promGw = new Pushgateway(gwUrl, { 
		timeout: 60000, 
		agent: new http.Agent({
			keepAlive: true,
			keepAliveMsecs: 300000,
			maxSockets: 5,
		}),
	}, register);

	return promGw;
}

export const promRegister = new Registry();
export const promGw = getPrometheusGw(PROMETHEUS_GW_URL, promRegister);


async function pushMetrics(workerId:string):Promise<void> {
	if (ENABLE_METRICS) {
		try {
			const { resp } = <{ resp: { statusCode: number } }> await promGw.push({ jobName: workerId });

			if (resp) {
				logger.debug(`Pushed metrics to prometheus: ${resp.statusCode}`);

			} else {
				logger.error('Pushing metrics but no response from Prometheus');
			}

		} catch(error) {
			if (error instanceof Error) {
				logger.error(`Cannot push prometheus metrics: ${error.message}`);
			}
		}

	} else {
		logger.warn('Metrics disabled');
	}
}

export { pushMetrics, getPrometheusGw }
