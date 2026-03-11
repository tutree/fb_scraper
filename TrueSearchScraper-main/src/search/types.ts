import type { Queue } from 'bullmq';

export type NameSearchArgs = {
	fullName:string;
	location:string;
	queue:Queue; 
	leadAttrs: TSNameSearchAttrs;
	workerId: string;
	ageFrom: string;
	ageTo: string;
};

export type TSNameSearchAttrs = {
	dataLabel: string;
	indeedAccountId?: string;
	originalSearchQuery: {
		fullName: string;
		location: string;
	};
};
