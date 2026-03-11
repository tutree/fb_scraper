import { writeFile } from 'node:fs/promises';

import { HEALTH_FILE_PATH } from '../config.js';


async function updateHealthInfo():Promise<void> {
	const healthData = JSON.stringify({
		lastProcessed: Date.now(),
	});

	await writeFile(HEALTH_FILE_PATH, healthData);
}

export { updateHealthInfo }
