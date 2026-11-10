package lab.rikkei.storex;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class DatabaseProbe implements ApplicationRunner {
    private static final Logger log = LoggerFactory.getLogger(DatabaseProbe.class);
    private final JdbcTemplate jdbc;

    public DatabaseProbe(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public QueryResult query() {
        QueryResult result = jdbc.queryForObject(
                "SELECT 1 AS query_result, current_database() AS database_name, "
                        + "inet_server_addr()::text AS server_address, inet_server_port() AS server_port",
                (rs, rowNum) -> new QueryResult(rs.getInt("query_result"),
                        rs.getString("database_name"), rs.getString("server_address"),
                        rs.getInt("server_port")));
        if (result == null || result.queryResult() != 1) {
            throw new IllegalStateException("Unexpected database probe result");
        }
        log.info("DB_CHECK SUCCESS database={} queryResult={} server={}:{}",
                result.database(), result.queryResult(), result.serverAddress(), result.serverPort());
        return result;
    }

    @Override
    public void run(ApplicationArguments args) {
        // Fail application startup if the configured datasource cannot execute real SQL.
        query();
    }

    public record QueryResult(int queryResult, String database, String serverAddress, int serverPort) {
    }
}
