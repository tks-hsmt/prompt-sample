require_relative 'helper'
require 'tempfile'

class RuleMatchFilterTest < Test::Unit::TestCase
  setup do
    Fluent::Test.setup
    @rules_file = Tempfile.new(['rules', '.csv'])
    @rules_file.write(<<~CSV)
      info,14,^10\\.0\\.0\\.[0-9]+$,.*login.*
      warn,12,.*,.*error.*
      ,,,
    CSV
    @rules_file.close
  end

  teardown do
    @rules_file.unlink
  end

  def run_filter(config, record)
    driver = Fluent::Test::Driver::Filter
      .new(Fluent::Plugin::RuleMatchFilter)
      .configure(config)
    driver.run(default_tag: 'test') do
      driver.feed(event_time, record)
    end
    driver.filtered_records.first
  end

  def base_config
    "rules_file #{@rules_file.path}"
  end

  sub_test_case '#configure' do
    test 'CSVが読み込まれ、空行は除外される' do
      driver = Fluent::Test::Driver::Filter
        .new(Fluent::Plugin::RuleMatchFilter)
        .configure(base_config)
      rules = driver.instance.instance_variable_get(:@rules)
      assert_equal 2, rules.size
    end
  end

  sub_test_case '#filter' do
    test '全条件一致で _matched に "matched" が入る' do
      record = run_filter(base_config, {
        'host' => '10.0.0.5',
        'pri' => '14',
        'message' => 'user login success'
      })
      assert_equal 'matched', record['_matched']
    end

    test 'pri 不一致なら _matched は nil' do
      record = run_filter(base_config, {
        'host' => '10.0.0.5',
        'pri' => '16',
        'message' => 'user login success'
      })
      assert_nil record['_matched']
    end

    test 'host の正規表現不一致なら _matched は nil' do
      record = run_filter(base_config, {
        'host' => '172.16.0.1',
        'pri' => '14',
        'message' => 'user login success'
      })
      assert_nil record['_matched']
    end

    test 'message の正規表現不一致なら _matched は nil' do
      record = run_filter(base_config, {
        'host' => '10.0.0.5',
        'pri' => '14',
        'message' => 'just a normal log'
      })
      assert_nil record['_matched']
    end

    test '2番目のルールにマッチする場合も _matched に "matched"' do
      record = run_filter(base_config, {
        'host' => 'any-host',
        'pri' => '12',
        'message' => 'system error occurred'
      })
      assert_equal 'matched', record['_matched']
    end
  end
end