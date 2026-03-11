import logger from '../logging.js';

import type { Collection } from 'mongodb';


export type TabProgressRecord = {
	startedAt: Date;
	sheetId: string;
	tabName: string;
	totalRows: number;
	lastProcessedRow: number;
};


async function tabProgressInit(
		tabProgressCollection:Collection<TabProgressRecord>, sheetId:string, tabName:string, totalRows:number
	):Promise<number> {

	const resp = await tabProgressCollection.findOne({ sheetId, tabName });

	if (resp) {
		return resp.lastProcessedRow;
	}

	logger.info('Creating new tab progress record...');

	await tabProgressCollection.insertOne({
		startedAt: new Date(),
		sheetId,
		tabName,
		totalRows,
		lastProcessedRow: 0,
	});

	return 0;
}

async function recordProcessedRow(
		tabProgressCollection:Collection<TabProgressRecord>, sheetId:string, tabName:string, lastProcessedRow:number
	):Promise<void> {

	const resp = await tabProgressCollection.findOne({ sheetId, tabName });

	if (!resp) {
		throw new Error('No progress record for this tab...');
	}

	if (resp && resp.lastProcessedRow < lastProcessedRow) {
		await tabProgressCollection.updateOne(
			{ sheetId, tabName },
			{
				$set: { lastProcessedRow }
			}
		);

	} else {
		logger.warn(`Just processed row: ${lastProcessedRow} but last recorded row ${resp.lastProcessedRow}`);
	}
}

async function markTabAsFinished(
		tabProgressCollection:Collection<TabProgressRecord>, sheetId:string, tabName:string, 
		lastProcessedRow:number, totalRows:number
	):Promise<void> {

	await tabProgressCollection.updateOne(
		{ sheetId, tabName },
		{
			$set: { lastProcessedRow, totalRows }
		}
	);
}

export { tabProgressInit, recordProcessedRow, markTabAsFinished }
