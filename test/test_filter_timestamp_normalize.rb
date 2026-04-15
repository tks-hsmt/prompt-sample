require_relative 'helper'

class TimestampNormalizeFilterTest < Test::Unit::TestCase
  setup do
    Fluent::Test.setup
  end

  def run_filter(config, record, time = event_time('2026-04-15 10:00:00 UTC'))
    driver = Fluent::Test::Driver::Filter
      .new(Fluent::Plugin::TimestampNormalizeFilter)
      .configure(config)
    driver.run(default_tag: 'test') do
      driver.feed(time, record)
    end
    driver.filtered_records.first
  end

  sub_test_case '#filter' do
    test 'ISO 8601 形式で timestamp フィールドが追加される' do
      record = run_filter('', { 'message' => 'hello' })
      assert_equal '2026-04-15T10:00:00.000Z', record['timestamp']
    end

    test '元のフィールドは保持される' do
      record = run_filter('', { 'message' => 'hello', 'host' => '10.0.0.1' })
      assert_equal 'hello',    record['message']
      assert_equal '10.0.0.1', record['host']
    end

    test 'field_name を変更できる' do
      record = run_filter('field_name event_time', { 'message' => 'x' })
      assert_equal '2026-04-15T10:00:00.000Z', record['event_time']
      assert_nil record['timestamp']
    end

    test 'format を変更できる' do
      record = run_filter('format %Y/%m/%d', { 'message' => 'x' })
      assert_equal '2026/04/15', record['timestamp']
    end
  end
end