package lab.rikkei.storex;

import java.time.Instant;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class DatabaseCheckController {
    private static final Logger log = LoggerFactory.getLogger(DatabaseCheckController.class);
    private final DatabaseProbe probe;

    public DatabaseCheckController(DatabaseProbe probe) {
        this.probe = probe;
    }

    @GetMapping("/db-check")
    public ResponseEntity<CheckResponse> check() {
        try {
            DatabaseProbe.QueryResult result = probe.query();
            return ResponseEntity.ok(new CheckResponse("UP", true, true, result.database(),
                    result.queryResult(), result.serverAddress(), result.serverPort(),
                    "SQL query executed successfully", Instant.now()));
        } catch (DataAccessException | IllegalStateException ex) {
            // Return no credentials, JDBC URL, or exception detail to callers.
            log.warn("DB_CHECK FAILURE type={}", ex.getClass().getSimpleName());
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).body(
                    new CheckResponse("DOWN", false, false, null, null, null, null,
                            "Database query failed", Instant.now()));
        }
    }

    public record CheckResponse(String status, boolean databaseReachable, boolean queryExecuted,
                                String database, Integer queryResult, String serverAddress,
                                Integer serverPort, String message, Instant timestamp) {
    }
}
