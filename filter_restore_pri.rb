require 'fluent/plugin/filter'

module Fluent::Plugin
  # RFC 5424 Facility / Severity から PRI 値を算出し、record に付与する。
  # in_syslog の severity_key / facility_key で文字列として record に入った
  # facility / severity を、RFC 5424 §6.2.1 の PRI = Facility * 8 + Severity
  # に基づいて計算する。
  class RestorePriFilter < Filter
    Fluent::Plugin.register_filter('restore_pri', self)

    # RFC 5424 Table 1 (Section 6.2.1): Facility Numerical Codes
    FACILITY_MAP = {
      "kern"=>0, "user"=>1, "mail"=>2, "daemon"=>3,
      "auth"=>4, "syslog"=>5, "lpr"=>6, "news"=>7,
      "uucp"=>8, "cron"=>9, "authpriv"=>10, "ftp"=>11,
      "ntp"=>12, "audit"=>13, "alert"=>14, "at"=>15,
      "local0"=>16, "local1"=>17, "local2"=>18, "local3"=>19,
      "local4"=>20, "local5"=>21, "local6"=>22, "local7"=>23
    }.freeze

    # RFC 5424 Table 2 (Section 6.2.1): Severity Numerical Codes
    SEVERITY_MAP = {
      "emerg"=>0, "alert"=>1, "crit"=>2, "err"=>3,
      "warn"=>4, "notice"=>5, "info"=>6, "debug"=>7
    }.freeze

    config_param :severity_field, :string, default: '_severity'
    config_param :facility_field, :string, default: '_facility'
    config_param :pri_field, :string, default: 'pri'

    def filter(tag, time, record)
      sev_name = record[@severity_field]
      fac_name = record[@facility_field]

      sev = SEVERITY_MAP[sev_name.to_s]
      fac = FACILITY_MAP[fac_name.to_s]

      if sev && fac
        record[@pri_field] = fac * 8 + sev
      else
        log.debug {
          "restore_pri: unknown severity/facility, pri not computed " \
          "severity=#{sev_name.inspect} facility=#{fac_name.inspect}"
        }
      end

      # Facility と Severity の元のフィールドは不要なので削除する
      record.delete(@severity_field)
      record.delete(@facility_field)

      record
    rescue => e
      log.warn "syslog_pri error: #{e.class}: #{e.message}"
      record
    end
  end
end
