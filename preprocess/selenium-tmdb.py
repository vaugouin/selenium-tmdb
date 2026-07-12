import time
import citizenphil as cp
import pymysql
from datetime import datetime, timedelta
from pathlib import Path

strprocessesexecutedprevious = cp.f_getservervariable("strseleniumtmdbprocessesexecuted",0)
strprocessesexecuteddesc = "List of processes executed in the Selenium TMDb preprocess"
cp.f_setservervariable("strseleniumtmdbprocessesexecutedprevious",strprocessesexecutedprevious,strprocessesexecuteddesc + " (previous execution)",0)
strprocessesexecuted = ""
cp.f_setservervariable("strseleniumtmdbprocessesexecuted",strprocessesexecuted,strprocessesexecuteddesc,0)

try:
    conn = cp.f_getconnection()
    with conn:
        with conn.cursor() as cursor:
            cursor3 = conn.cursor()
            # Start timing the script execution
            start_time = time.time()
            strnow = datetime.now(cp.paris_tz).strftime("%Y-%m-%d %H:%M:%S")
            cp.f_setservervariable("strseleniumtmdbstartdatetime",strnow,"Date and time of the last start of the Selenium TMDb preprocess",0)
            strtotalruntimedesc = "Total runtime of the Selenium TMDb preprocess"
            strtotalruntimeprevious = cp.f_getservervariable("strseleniumtmdbtotalruntime",0)
            cp.f_setservervariable("strseleniumtmdbtotalruntimeprevious",strtotalruntimeprevious,strtotalruntimedesc + " (previous execution)",0)
            strtotalruntime = "RUNNING"
            cp.f_setservervariable("strseleniumtmdbtotalruntime",strtotalruntime,strtotalruntimedesc,0)

            intdownloadok = True
            # Now handling SQL queries
            arrprocessscope = {1: 'SQL queries'}
            for intindex, strdesc in arrprocessscope.items():
                strprocessesexecuted += str(intindex) + ", "
                cp.f_setservervariable("strseleniumtmdbprocessesexecuted",strprocessesexecuted,strprocessesexecuteddesc,0)
                # Get the current date and time
                datnow = datetime.now(cp.paris_tz)
                # Compute the date and time 14 days ago
                delta = timedelta(days=14)
                datjminus14 = datnow - delta
                strdatjminus14 = datjminus14.strftime("%Y-%m-%d %H:%M:%S")
                # Print the result (optional)
                #print("Current Date and Time:", current_datetime)
                #print("Date and Time 14 days ago:", past_datetime)
                # Now use the YTS API to import data into the MySQL database
                # print(intindex, value)
                strcurrentprocess = ""
                strsql = ""
                if intindex == 1:
                    strcurrentprocess = f"{intindex}: executing SQL files"
                    print(strcurrentprocess)
                    cp.f_setservervariable("strseleniumtmdbcurrentprocess",strcurrentprocess,"Current process in the Selenium TMDb preprocess",0)

                    strdescvarname = strdesc.replace(" ", "")
                    datnow = datetime.now(cp.paris_tz)
                    strdate = datnow.strftime("%Y%m%d")

                    strscriptdir = Path(__file__).resolve().parent
                    arrsqlfiles = sorted(strscriptdir.glob("*.sql"))
                    print(f"SQL folder: {strscriptdir}")
                    print(f"Found {len(arrsqlfiles)} .sql files")
                    lngcount = 0

                    for sqlfilepath in arrsqlfiles:
                        sqlbasename = sqlfilepath.stem
                        outdir = strscriptdir / sqlbasename
                        outdir.mkdir(parents=True, exist_ok=True)
                        outfilepath = outdir / f"{sqlbasename}-{strdate}.csv"

                        with open(sqlfilepath, "r", encoding="utf-8") as fsql:
                            strsql = fsql.read().strip()

                        if strsql == "":
                            continue

                        print(f"Executing: {sqlfilepath.name}")
                        cursor.execute(strsql)
                        results = cursor.fetchall()

                        arrcolumns = []
                        if cursor.description is not None:
                            arrcolumns = [col[0] for col in cursor.description]

                        with open(outfilepath, "w", newline="", encoding="utf-8") as fcsv:
                            def f_csv_escape_value(val):
                                if val is None:
                                    return "NULL"
                                sval = str(val)
                                sval = sval.replace('"', '""')
                                return f'"{sval}"'

                            if arrcolumns:
                                fcsv.write(";".join([f_csv_escape_value(col) for col in arrcolumns]) + "\n")

                            for row in results:
                                if isinstance(row, dict):
                                    vals = [row.get(col) for col in arrcolumns]
                                else:
                                    vals = list(row)

                                fcsv.write(";".join([f_csv_escape_value(v) for v in vals]) + "\n")

                        lngcount += 1
                        cp.f_setservervariable(
                            "strseleniumtmdbprocess" + str(intindex) + strdescvarname + "count",
                            str(lngcount),
                            "Count of SQL files processed for process " + str(intindex) + " : " + strdesc + "",
                            0,
                        )
                        strnow = datetime.now(cp.paris_tz).strftime("%Y-%m-%d %H:%M:%S")
                        cp.f_setservervariable("strseleniumtmdbdatetime",strnow,"Date and time of the last crawled record using the YTS API",0)
            strsql = ""
            strcurrentprocess = ""
            cp.f_setservervariable("strseleniumtmdbcurrentprocess",strcurrentprocess,"Current process in the Selenium TMDb preprocess",0)
            strnow = datetime.now(cp.paris_tz).strftime("%Y-%m-%d %H:%M:%S")
            cp.f_setservervariable("strseleniumtmdbenddatetime",strnow,"Date and time of the Selenium TMDb preprocess ending",0)
            # Calculate total runtime and convert to readable format
            end_time = time.time()
            strtotalruntime = int(end_time - start_time)  # Total runtime in seconds
            cp.f_setservervariable("strseleniumtmdbtotalruntimesecond",str(strtotalruntime),strtotalruntimedesc,0)
            readable_duration = cp.convert_seconds_to_duration(strtotalruntime)
            cp.f_setservervariable("strseleniumtmdbtotalruntime",readable_duration,strtotalruntimedesc,0)
            print(f"Total runtime: {strtotalruntime} seconds ({readable_duration})")
    print("Process completed")
except pymysql.MySQLError as e:
    print(f"❌ MySQL Error: {e}")
    conn = getattr(cp, "connectioncp", None)
    if conn is not None and getattr(conn, "open", False):
        conn.rollback()
