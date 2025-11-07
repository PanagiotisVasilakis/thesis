import logging
import time
logger = logging.getLogger(__name__)

def check_expiration_time(expire_time):
    year = int(expire_time[0:4])
    month = int(expire_time[5:7])
    day = int(expire_time[8:10])
    hour = int(expire_time[11:13])
    minute = int(expire_time[14:16])
    sec = int(expire_time[17:19])

    time_now = time.localtime()
    logger.debug("Current time: %s", time.asctime(time_now))
    
    if year>time_now[0]:
        logger.debug("Year: %s, current year: %s", year, time_now[0])
        return True
    elif year == time_now[0]:
        if month > time_now[1]:
            logger.debug("Month: %s, current month: %s", month, time_now[1])
            return True
        elif(month == time_now[1]):
            if(day>time_now[2]):
                logger.debug("Day: %s, current day: %s", day, time_now[2])
                return True
            elif(day==time_now[2]):
                logger.debug("Day == day now %s %s", day, time_now[2])
                if(hour>time_now[3]):
                    logger.debug("Hour: %s, current hour: %s", hour, time_now[3])
                    return True
                elif(hour==time_now[3]):
                    logger.debug("Time == time now %s %s", hour, time_now[3])
                    if(minute>time_now[4]):
                        logger.debug("%s %s", minute, time_now[4])
                        return True
                    elif(minute==time_now[4]):
                        logger.debug("Minute == minute now %s %s", minute, time_now[4])
                        if(sec>=time_now[5]):
                            logger.debug("%s %s", sec, time_now[5])
                            return True
                        else:
                            return False
                    else:
                        return False
                else:
                    return False
            else:
                return False
        else:
            return False
    else:
        return False

def check_numberOfReports(maximum_number_of_reports: int) -> bool:
    if maximum_number_of_reports >= 1:
        return True
    else:
        logging.warning("Subscription has expired (maximum number of reports")
        return False
