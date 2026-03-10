class PageAlreadyProcessedError extends Error {
    constructor(message:string) {
        super(message);
        this.name = this.constructor.name;
    }
}

class PageReturnedNothingError extends Error {
    constructor(message:string) {
        super(message);
        this.name = this.constructor.name;
    }
}

class CaptchaError extends Error {
    constructor(message:string) {
        super(message);
        this.name = this.constructor.name;
    }
}

export { PageAlreadyProcessedError, PageReturnedNothingError, CaptchaError }
