import { Redis as IORedis } from 'ioredis';
import { Queue } from 'bullmq';

import { JOB_PROCESSING_ATTEMPTS } from '../config.js';


async function submitIndeedResumeMatching(
		indeedResumeMatchingQueue:Queue, indeedAccountId:string, dataLabel:string
	):Promise<void> {

	await indeedResumeMatchingQueue.add(
		'indeedAccountId', 
		{ 
			indeedAccountId, dataLabel 
		}, {
			removeOnComplete: true,
			attempts: JOB_PROCESSING_ATTEMPTS,
		}
	);
}

export { submitIndeedResumeMatching }
